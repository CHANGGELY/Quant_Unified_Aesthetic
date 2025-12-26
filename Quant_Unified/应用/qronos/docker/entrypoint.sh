#!/bin/bash

# 量化交易框架管理系统 Docker 容器启动脚本
#
# 该脚本负责：
# 1. 初始化应用环境
# 2. 生成随机端口和前缀配置
# 3. 启动数据库初始化
# 4. 创建PM2配置并启动FastAPI和Nginx服务
#
# Author: 项目团队
# Date: 2024

set -e

echo "=========================================="
echo "量化交易框架管理系统正在启动..."
echo "=========================================="

# PM2配置优化：解决挂载目录的Unix套接字问题
# 策略：运行时数据在容器内，持久化配置通过备份/恢复机制
export PM2_HOME="/app/.pm2-runtime"
export PM2_PERSISTENT_DIR="/app/.pm2"

echo "PM2配置策略："
echo "- 运行时目录: ${PM2_HOME}"
echo "- 持久化目录: ${PM2_PERSISTENT_DIR}"

# 创建PM2运行时目录（容器内，不挂载）
mkdir -p "${PM2_HOME}"

# 创建PM2持久化目录（可挂载）
mkdir -p "${PM2_PERSISTENT_DIR}/logs" \
         "${PM2_PERSISTENT_DIR}/pids" \
         "${PM2_PERSISTENT_DIR}/conf"

# 设置PM2环境变量
echo "export PM2_HOME=${PM2_HOME}" >> /etc/environment
echo "export PM2_HOME=${PM2_HOME}" >> /root/.bashrc
source /root/.bashrc

# 生成随机端口配置（如果不存在）
if [ ! -f /app/apps/qronos/data/port.txt ]; then
    echo "未找到 port.txt 配置，程序退出"
    exit 1
else
    RANDOM_PORT=$(cat /app/apps/qronos/data/port.txt)
    echo "使用现有端口配置: ${RANDOM_PORT}"
fi

# 生成随机前缀配置（如果不存在）
if [ ! -f /app/apps/qronos/data/prefix.txt ]; then
    echo "未找到 prefix.txt 配置，程序退出"
    exit 1
else
    RANDOM_PREFIX=$(cat /app/apps/qronos/data/prefix.txt)
    echo "使用现有API前缀配置: ${RANDOM_PREFIX}"
fi

# 显示配置信息
echo ""
echo "📋 系统配置信息:"
echo "🔗 开放端口: ${RANDOM_PORT}"
echo "🔗 URL前缀: /${RANDOM_PREFIX}"
echo ""


# 创建FastAPI应用的PM2配置文件
echo "创建PM2配置文件..."
cat > /app/apps/qronos/startup.json << EOF
{
  "apps": [
    {
      "name": "qronos-main",
      "script": "/app/apps/qronos/main.py",
      "interpreter": "python",
      "args": "",
      "exec_mode": "fork",
      "merge_logs": false,
      "watch": false,
      "log_date_format": "YYYY-MM-DD HH:mm:ss.SSS Z",
      "error_file": "/app/apps/qronos/logs/qronos-main-error.log",
      "out_file": "/app/apps/qronos/logs/qronos-main-out.log",
      "log_file": "/app/apps/qronos/logs/qronos-main.log"
    }
  ]
}
EOF

echo "PM2配置文件创建完成"

# 初始化PM2（使用容器内运行时目录）
echo "初始化PM2进程管理器..."
export PATH="/usr/bin:$PATH"

# 确保PM2守护进程启动（避免挂载目录的套接字问题）
echo "启动PM2守护进程..."
pm2 ping > /dev/null 2>&1 || pm2 startup > /dev/null 2>&1 || true

# 验证pm2-logrotate插件状态
echo "验证pm2-logrotate插件状态..."
if pm2 describe pm2-logrotate > /dev/null 2>&1; then
    echo "✅ pm2-logrotate插件已就绪"
else
    echo "⚠️  pm2-logrotate插件未找到，尝试重新安装..."
    pm2 install pm2-logrotate > /dev/null 2>&1 || echo "pm2-logrotate安装出现警告，继续执行..."
fi

# 恢复之前的PM2进程（如果存在）
echo "检查是否有之前的PM2配置需要恢复..."
if [ -f "${PM2_PERSISTENT_DIR}/conf/dump.pm2" ]; then
    echo "发现之前的PM2配置，尝试恢复..."
    cp "${PM2_PERSISTENT_DIR}/conf/dump.pm2" "${PM2_HOME}/dump.pm2" 2>/dev/null || true
    pm2 resurrect > /dev/null 2>&1 || echo "恢复PM2配置时出现警告，将启动新配置..."
fi

# 使用PM2启动FastAPI应用
echo "使用PM2启动FastAPI应用..."
pm2 start /app/apps/qronos/startup.json

# 等待FastAPI启动
echo "等待FastAPI服务启动..."
sleep 5

# 检查PM2进程状态
echo "检查PM2进程状态..."
pm2 list

# 保存PM2进程列表和配置到持久化目录
echo "保存PM2进程配置到持久化目录..."
pm2 save --force > /dev/null 2>&1 || true
# 备份配置文件到持久化目录
cp "${PM2_HOME}/dump.pm2" "${PM2_PERSISTENT_DIR}/conf/dump.pm2" 2>/dev/null || true
echo "PM2配置已保存到持久化目录，支持容器重启恢复"

# 设置定期备份PM2配置的函数
setup_pm2_backup() {
    echo "设置PM2配置定期备份..."
    (
        while true; do
            sleep 300  # 每5分钟备份一次
            pm2 save --force > /dev/null 2>&1 || true
            cp "${PM2_HOME}/dump.pm2" "${PM2_PERSISTENT_DIR}/conf/dump.pm2" 2>/dev/null || true
        done
    ) &
}

# 启动备份任务
setup_pm2_backup

# 生成动态Nginx配置
echo "生成动态Nginx配置..."
sed "s/\${API_PREFIX}/${RANDOM_PREFIX}/g" \
    /etc/nginx/conf.d/qronos.conf.template > /etc/nginx/conf.d/qronos.conf

echo "Nginx配置已生成，API前缀: /${RANDOM_PREFIX}, 端口: ${RANDOM_PORT}"

# 检查前端文件并生成备用页面（如果需要）
echo "检查前端文件..."
if [ ! -f /var/www/html/index.html ]; then
    echo "前端文件不存在，程序退出"
    exit 1
fi

# 检查Nginx配置
echo "检查Nginx配置..."
nginx -t

echo "=========================================="
echo "环境初始化完成，启动服务..."
echo "🔗 服务端口: ${RANDOM_PORT}"
echo "🔗 API前缀: /${RANDOM_PREFIX}"
echo "🌐 Web访问地址: http://localhost:${RANDOM_PORT}/${RANDOM_PREFIX}/"
echo "📊 PM2监控: docker exec -it <container> pm2 list"
echo "💾 PM2配置: ${PM2_PERSISTENT_DIR}/conf/dump.pm2"
echo "=========================================="

# 执行传入的命令
exec "$@"
