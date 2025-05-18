#!/usr/bin/env python3
# src/reles_client/client.py

import socket, time, threading, pickle, os
from configparser import ConfigParser
import mpsched, torch
from replay_memory import ReplayMemory
from agent import Online_Agent, Offline_Agent
from naf_lstm import NAF_LSTM

def main():
    # ——1) 读取配置
    cfg = ConfigParser()
    cfg.read('config.ini')
    SERVER_IP    = cfg.get('server','ip')
    SERVER_PORT  = cfg.getint('server','port')
    MEMORY_FILE  = cfg.get('replaymemory','memory')
    AGENT_FILE   = cfg.get('nafcnn','agent')
    INTERVAL     = cfg.getfloat('train','interval')
    EPISODES     = cfg.getint('train','episode')
    BATCH_SIZE   = cfg.getint('train','batch_size')
    MAX_SUBFLOWS = cfg.getint('env','max_num_subflows')

    # ——2) 初始化或加载 ReplayMemory
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE,'rb') as f:
            memory = pickle.load(f)
    else:
        memory = ReplayMemory(cfg.getint('replaymemory','capacity'))

    # ——3) 初始化模型（如果还没有）
    if not os.path.exists(AGENT_FILE):
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

    # ——4) 离线 Agent（daemon）
    off_agent = Offline_Agent(cfg=cfg, model=AGENT_FILE, memory=memory,
                              event=threading.Event())
    off_agent.daemon = True

    # ——5) 主循环：EPISODES 次主动上传 + 在线调度 + 离线训练
    FILES = ["64kb.dat","2mb.dat","8mb.dat","64mb.dat"]
    for ep in range(EPISODES):
        fname = FILES[ep % len(FILES)]
        print(f"[Episode {ep+1}/{EPISODES}] Uploading {fname}")

        # 5.1 建立 TCP 连接
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((SERVER_IP, SERVER_PORT))
        fd = sock.fileno()

        # 5.2 启动 Online Agent 并触发 event
        transfer_event = threading.Event()
        on_agent = Online_Agent(fd=fd, cfg=cfg,
                                memory=memory, event=transfer_event)
        on_agent.start()
        transfer_event.set()

        # 5.3 读取文件、构造 HTTP POST，并一次性发送
        with open(fname, 'rb') as f:
            data = f.read()
        header = (
            f"POST /{fname} HTTP/1.1\r\n"
            f"Host: {SERVER_IP}\r\n"
            f"Content-Length: {len(data)}\r\n"
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        sock.send(header + data)

        # 5.4 完成后清理
        transfer_event.clear()
        sock.close()

        # 5.5 启动 Offline Agent 做一次离线训练（如果条件满足）
        if len(memory) > BATCH_SIZE and not off_agent.is_alive():
            off_agent.start()

        # 5.6 等待一段时间再下一轮
        time.sleep(INTERVAL)

    # ——6) 全部完成后保存 memory
    with open(MEMORY_FILE,'wb') as f:
        pickle.dump(memory, f)

    print("All episodes done; model saved to", AGENT_FILE)

if __name__ == "__main__":
    main()
