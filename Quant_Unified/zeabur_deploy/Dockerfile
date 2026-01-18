# 使用官方 Python 3.12 轻量镜像
FROM python:3.12-slim

# 工作目录
WORKDIR /app

# 时区（日志时间更直观）
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Zeabur 默认端口（平台会注入 PORT 环境变量；这里给默认值方便本地 docker run）
ENV PORT=8080

# 关键：不缓冲 stdout，保证日志实时输出（符合“显式运行”要求）
ENV PYTHONUNBUFFERED=1

# 让 `import 策略仓库...` 等包在容器里也能稳定工作
ENV PYTHONPATH=/app/Quant_Unified

# 安装依赖
COPY Quant_Unified/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 复制主代码（Zeabur 部署只需要主代码这一份，不再复制一套 zeabur_deploy 的“镜像代码”）
COPY Quant_Unified /app/Quant_Unified

# 入口脚本（在 Quant_Unified/zeabur_deploy/entrypoint.sh）
RUN chmod +x /app/Quant_Unified/zeabur_deploy/entrypoint.sh

# 暴露端口（仅做说明；Zeabur 实际会用 PORT 环境变量）
EXPOSE 8080

# 启动入口：实盘策略（策略仓库/八号香农策略/real_trading.py）
CMD ["/app/Quant_Unified/zeabur_deploy/entrypoint.sh"]

