# 使用 Python 3.12 作为基础镜像
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖 (编译 pandas/numpy 可能需要)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY Quant_Unified/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install flask  # 增加一个简单的 web 服务用于白嫖 HF 探针

# 复制整个项目代码
COPY . .

# 设置环境变量 (HF 默认使用 7860 端口)
ENV PORT=7860
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# 创建一个简单的监控探针脚本
RUN echo 'from flask import Flask; import os; app = Flask(__name__); @app.route("/")\ndef hello(): return "Quant Collector is Running!";\nif __name__ == "__main__": app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))' > /app/hf_probe.py

# 启动脚本：同时运行采集器和监控探针
CMD python /app/Quant_Unified/服务/数据采集/启动采集.py & python /app/hf_probe.py
