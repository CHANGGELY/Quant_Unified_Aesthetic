#!/usr/bin/env bash
set -euo pipefail

# 这个脚本是干嘛的？
#   这是 Zeabur 容器的“启动按钮”：
#   - 用 python -u：保证日志实时输出（不然你在 Zeabur 控制台会看到“半天没动静”）
#   - 用 -X utf8：保证中文日志/文件路径不乱码

echo "🚀 启动 8号香农策略（实盘脚本）..."
echo "   - 脚本: Quant_Unified/策略仓库/八号香农策略/real_trading.py"
echo "   - 提示: 请在 Zeabur 环境变量里配置 USE_REAL_TRADING / API Key 等"

python -X utf8 -u /app/Quant_Unified/策略仓库/八号香农策略/real_trading.py

