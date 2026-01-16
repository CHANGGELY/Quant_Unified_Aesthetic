# 使用官方 Python 3.10 轻量镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置时区为上海 (CST)
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Zeabur 默认端口
ENV PORT=8080

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制整个项目代码
COPY . .

# 赋予启动脚本执行权限
RUN chmod +x deployment_hf/zeabur_entrypoint.sh
RUN mv deployment_hf/zeabur_entrypoint.sh ./entrypoint.sh

# 暴露端口
EXPOSE 8080

# 启动入口
CMD ["./entrypoint.sh"]
