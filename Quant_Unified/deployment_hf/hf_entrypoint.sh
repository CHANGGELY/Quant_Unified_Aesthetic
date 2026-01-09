#!/bin/bash

# 打印环境信息
echo "🚀 正在启动 8号香农策略容器..."
echo "当前时间: $(date)"
echo "当前目录: $(pwd)"
echo "Python路径: $(which python)"

# 0. 准备配置文件
# 如果设置了环境变量 allow_taker，可以在这里动态修改 config_live.py (可选)

# 1. 后台启动实盘策略
# 使用 nohup 后台运行，并将标准输出和错误重定向到 runtime.log
echo ">>> 启动策略主程序 (Background)..."
# 为了确保 flush 及时，加上 -u
nohup python -u -X utf8 策略仓库/八号香农策略/real_trading.py > runtime.log 2>&1 &

# 获取策略 PID
STRATEGY_PID=$!
echo "策略进程 ID: $STRATEGY_PID"

# 2. 前台启动 Streamlit 监控面板
# 这是主进程，不能退出，否则 Docker 容器会停止。
# 并且它提供了 Web 服务端口 7860，满足 HF Spaces 的要求。
echo ">>> 启动 Streamlit 监控面板 (Foreground)..."
streamlit run deployment_hf/hf_monitor.py --server.port 7860 --server.address 0.0.0.0
