#!/usr/bin/env python3
# src/receive/server_upload.py

from http.server import HTTPServer, BaseHTTPRequestHandler
from configparser import ConfigParser
import os

# 读取配置
cfg = ConfigParser()
cfg.read('config.ini')
IP   = cfg.get('server','ip')
PORT = cfg.getint('server','port')

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        data = self.rfile.read(length)  # 读取上传的整个文件
        # 保存文件：使用请求路径作为文件名
        fname = os.path.basename(self.path)
        with open(os.path.join(UPLOAD_DIR, fname), 'wb') as f:
            f.write(data)
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # 关闭默认日志

if __name__ == '__main__':
    print(f"Upload server listening on {IP}:{PORT}, saving to '{UPLOAD_DIR}/'")
    HTTPServer((IP, PORT), Handler).serve_forever()
