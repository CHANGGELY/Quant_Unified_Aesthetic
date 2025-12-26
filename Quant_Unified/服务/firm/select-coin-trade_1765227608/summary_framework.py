"""
Quant Unified 量化交易系统
summary_framework.py
"""
import time
import os
import sys
from datetime import datetime

# Add current directory to path
sys.path.append(os.getcwd())

def run_summary_loop():
    print(f"[{datetime.now()}] 汇总看板框架启动...")
    while True:
        try:
            # 这里可以添加读取账户权益、持仓统计的代码
            # 暂时只做心跳日志
            print(f"[{datetime.now()}] 汇总数据更新完成 (模拟)")
            
            # 每1分钟更新一次
            time.sleep(60)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)

if __name__ == '__main__':
    run_summary_loop()
