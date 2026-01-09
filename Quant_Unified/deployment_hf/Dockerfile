# 使用官方 Python 3.10 轻量镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置时区为上海 (CST)
# 这一步非常关键，否则日志时间和交易时间会差8小时
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 安装系统依赖 (如有需要)
# RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制整个项目代码
# 注意：这会将 Quant_Unified 下的所有内容复制到 /app
COPY . .

# 创建一个非 root 用户 (HF Spaces 推荐)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

# 暴露 Streamlit 端口
EXPOSE 7860

# 赋予启动脚本执行权限
RUN chmod +x deployment_hf/hf_entrypoint.sh

# 启动入口
CMD ["./deployment_hf/hf_entrypoint.sh"]
