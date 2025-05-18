#!/usr/bin/env python3
import sys
import os
import time
import threading
import pickle
import shutil
from datetime import datetime
import socket

import mpsched
import torch
from configparser import ConfigParser
from replay_memory import ReplayMemory
from agent import Online_Agent, Offline_Agent
from naf_lstm import NAF_LSTM

def main(argv):
    # ——— 1) 读配置 ——————————————————————————————
    cfg = ConfigParser()
    cfg.read('config.ini')
    SERVER_IP     = cfg.get('server','ip')
    SERVER_PORT   = cfg.getint('server','port')
    MEMORY_FILE   = cfg.get('replaymemory','memory')
    AGENT_FILE    = cfg.get('nafcnn','agent')
    INTERVAL      = cfg.getfloat('train','interval')
    EPISODES      = cfg.getint('train','episode')
    BATCH_SIZE    = cfg.getint('train','batch_size')
    MAX_SUBFLOWS  = cfg.getint('env','max_num_subflows')

    # ——— 2) 解析命令行参数 ——————————————————————————
    # CONTINUE_TRAIN=1: 加载已有 memory & agent 继续训练/推理
    # CONTINUE_TRAIN=0: 从头训练（并备份旧 agent）
    CONTINUE_TRAIN = 1
    scenario = 'default'
    if len(argv) >= 1:
        CONTINUE_TRAIN = int(argv[0])
    if len(argv) >= 2:
        scenario = argv[1]
    print(f"CONTINUE_TRAIN={CONTINUE_TRAIN}, scenario='{scenario}'")

    # ——— 3) 初始化或加载 ReplayMemory ——————————————————
    if os.path.exists(MEMORY_FILE) and CONTINUE_TRAIN:
        with open(MEMORY_FILE,'rb') as f:
            try:
                memory = pickle.load(f)
            except EOFError:
                print("Memory file corrupted, creating new ReplayMemory")
                memory = ReplayMemory(cfg.getint('replaymemory','capacity'))
    else:
        memory = ReplayMemory(cfg.getint('replaymemory','capacity'))

    # ——— 4) 备份旧 Agent 并初始化新模型 —————————————
    now = datetime.now().replace(microsecond=0).isoformat()
    if CONTINUE_TRAIN == 0 and os.path.exists(AGENT_FILE):
        os.makedirs("trained_models", exist_ok=True)
        shutil.move(AGENT_FILE, f"trained_models/agent_{scenario}_{now}.pkl")

    if not os.path.exists(AGENT_FILE) or CONTINUE_TRAIN == 0:
        num_inputs   = cfg.getint('env','k') * MAX_SUBFLOWS * 5
        action_space = MAX_SUBFLOWS
        agent_net = NAF_LSTM(
            gamma=cfg.getfloat('nafcnn','gamma'),
            tau=cfg.getfloat('nafcnn','tau'),
            hidden_size=cfg.getint('nafcnn','hidden_size'),
            num_inputs=num_inputs,
            action_space=action_space
        )
        torch.save(agent_net, AGENT_FILE)

    # ——— 5) 初始化 Offline Agent ——————————————————————
    off_event = threading.Event()
    off_agent = Offline_Agent(cfg=cfg, model=AGENT_FILE, memory=memory, event=off_event)
    off_agent.daemon = True

    # ——— 6) 主循环：EPISODES 次主动上传 + 调度 + 离线训练 —————————
    FILES = ["64kb.dat","2mb.dat","8mb.dat","64mb.dat"]
    for ep in range(EPISODES):
        fname = FILES[ep % len(FILES)]
        print(f"[Episode {ep+1}/{EPISODES}] Uploading {fname}")

        # —– 6.1 建立 TCP 连接 ——————————————————————
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((SERVER_IP, SERVER_PORT))
        fd = sock.fileno()

        # —– 6.2 启动 Online Agent 并 set 事件 ———————————————
        transfer_event = threading.Event()
        on_agent = Online_Agent(fd=fd, cfg=cfg, memory=memory, event=transfer_event)
        on_agent.start()
        transfer_event.set()

        # —– 6.3 读取文件并 HTTP POST ————————————————
        with open(fname, 'rb') as f:
            data = f.read()
        header = (
            f"POST /{fname} HTTP/1.1\r\n"
            f"Host: {SERVER_IP}\r\n"
            f"Content-Length: {len(data)}\r\n"
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        sock.send(header + data)

        # —– 6.4 清理 ——————————————————————————
        transfer_event.clear()
        sock.close()

        # —– 6.5 启动 Offline Agent（若经验足够） ————————————
        if len(memory) > BATCH_SIZE and not off_agent.is_alive():
            off_agent.start()

        # —– 6.6 等待下次迭代 ——————————————————————
        time.sleep(INTERVAL)

    # ——— 7) 全部完成后保存 memory ————————————————————
    with open(MEMORY_FILE,'wb') as f:
        pickle.dump(memory, f)

    print(f"All {EPISODES} episodes done; model saved to '{AGENT_FILE}'")

if __name__ == "__main__":
    main(sys.argv[1:])
