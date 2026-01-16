#!/bin/bash

# 启动 实盘策略 (后端核心)
# 使用 python -u 确保日志实时输出
echo "🚀 Starting Shannon Strategy (Headless Mode)..."
python -u 策略仓库/八号香农策略/real_trading.py
