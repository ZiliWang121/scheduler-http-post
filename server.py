#!/usr/bin/python3

import socket
import sys 
import getopt
import mpsched
from configparser import ConfigParser
import time
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import re
import random
import sqlite3

def main(argv):
	cfg = ConfigParser()
	cfg.read('config.ini')
	IP = cfg.get('server','ip')
	PORT = cfg.getint('server','port')
	FILE = cfg.get('file','file')
	FILES = ["64kb.dat","2mb.dat","8mb.dat","64mb.dat"]
	num_iterations = 150
	if len(argv) != 0:
		FILE = argv[1]
		num_iterations = int(argv[0])
	print(FILE,num_iterations)
	performance_metrics = []
	np.random.seed(42)
	for l in range(num_iterations):
		ooq = [0,0,0]
		if FILE == "random" and num_iterations > 150: #random.dat
			FILE2 = np.random.choice(FILES,p=[0, 0.9, 0, 0.1])
		elif FILE == "random" and num_iterations == 150:
			FILE2 = np.random.choice(FILES,p=[0.3,0.35,0.3,0.05])
		else:
			FILE2 = FILE
		
		print(FILE2)
		sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
		
		sock.connect((IP,PORT))
		sock.send(b"GET /" + bytes(FILE2,"utf8") + b" HTTP/1.1\r\nHost:10.0.2.10\r\n\r\n")
		try:
			info = sock.recv(17)
		except TimeoutError:
			print("timeout error")
		
		fd = sock.fileno()
		mpsched.persist_state(fd)
		
		if str(info,encoding='utf8').find("OK") != -1:
			
			fp = open(FILE2,'wb')
			if not fp:
				print("open file error.\n")
			else:
				start = time.time()
				while(True):
					subs = (mpsched.get_sub_info(fd))
					buff = sock.recv(2048)
					if not buff:
						break
					else:	
						fp.write(buff)
				fp.close()
				stop = time.time() #completion time from start of TCP until end of transfer 
				if l >= 30:
					for i in range(len(subs)):
						print(subs[i][8],subs[i][7])
						if subs[i][8] == 16842762: #16842762 #3053496512 16777226 subflow 0 in user space
							ooq[0] = subs[i][7]
						elif subs[i][8] == 33685514: #2868947136 #33685514: #33554442
							ooq[1] = subs[i][7]
						elif subs[i][8] == 50528266:
							ooq[2] = subs[i][7]
						else:
							ooq[i] = 0
					completion_time = stop-start
					print(completion_time)
					if FILE2.find("kb") != -1:
						file_size = int(re.findall(r'\d+',FILE2)[0])/1000
					else: 
						file_size = int(re.findall(r'\d+',FILE2)[0]) 
					print(file_size)
					throughput = file_size/completion_time
					performance_metrics.append({"completion time": completion_time,
									"throughput": throughput,
									"out-of-order 4G": ooq[0],
									"out-of-order 5G": ooq[1],
									"out-of-order WLAN": ooq[2]})
				
				
		else:
			print('no file {} in server: {}'.format(FILE2,IP))
		sock.close()
		time.sleep(0.25)
	df = pd.DataFrame(performance_metrics)
	df.to_csv("client_metrics.csv",index=False)
	print("finish transfer")
		
		
if __name__ == '__main__':
	main(sys.argv[1:])
