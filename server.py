#!/usr/bin/env python3
# src/receive/server.py

import os, sys, time, pickle, signal, threading, socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from configparser import ConfigParser
import mpsched
import pandas as pd
import re
import numpy as np

# ——1) 读配置
cfg = ConfigParser()
cfg.read('config.ini')
IP   = cfg.get('server','ip')
PORT = cfg.getint('server','port')

# ——2) 全局存放指标
performance_metrics = []
metrics_lock = threading.Lock()
iteration = 0

# ——3) SIGINT 捕获，优雅退出并保存 CSV
def handle_exit(signum, frame):
    global performance_metrics
    df = pd.DataFrame(performance_metrics)
    df.to_csv("server_metrics.csv", index=False)
    print(f"\nSaved {len(performance_metrics)} records to server_metrics.csv")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)

class UploadHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        global iteration
        # 3.1 解析 Content-Length
        length = int(self.headers.get('Content-Length', 0))
        fd = self.request.fileno()

        # 3.2 持久化 mpsched 状态
        mpsched.persist_state(fd)

        # 3.3 接收并写入 /dev/null（不保存文件）
        start = time.time()
        received = 0
        subs = None
        # 按 2048 字节块循环读
        while received < length:
            chunk = self.rfile.read(min(2048, length - received))
            if not chunk:
                break
            received += len(chunk)
            # 采集子流状态
            subs = mpsched.get_sub_info(fd)
        stop = time.time()

        # 3.4 只有从第 30 次开始，才做指标记录（和原 client.py 一致）
        if iteration >= 30:
            ooq = [0]*len(subs)
            # 原 code 里比对 subs[i][8]（path_index mask）来分流 out-of-order
            for i,s in enumerate(subs):
                path_mask = s[8]
                ooq_val = s[7]
                # 依照你之前的三条子流 mapping
                if path_mask == 16842762:
                    ooq[0] = ooq_val
                elif path_mask == 33685514:
                    ooq[1] = ooq_val
                else:
                    ooq[2] = ooq_val
            completion_time = stop - start
            # 根据长度判断 MB vs KB
            if self.path.endswith("kb.dat"):
                size_mb = (int(re.findall(r'\d+', self.path)[0]) / 1000)
            else:
                size_mb = int(re.findall(r'\d+', self.path)[0])
            throughput = size_mb / completion_time

            with metrics_lock:
                performance_metrics.append({
                    "filename": os.path.basename(self.path),
                    "completion time": completion_time,
                    "throughput": throughput,
                    "out-of-order 4G": ooq[0],
                    "out-of-order 5G": ooq[1],
                    "out-of-order WLAN": ooq[2]
                })

        iteration += 1

        # 3.5 回复客户端
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # 关闭默认日志

if __name__ == '__main__':
    os.makedirs("uploads", exist_ok=True)
    print(f"Starting upload+metrics server on {IP}:{PORT}")
    server = HTTPServer((IP, PORT), UploadHandler)
    server.serve_forever()
