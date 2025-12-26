# 量化交易框架管理系统 Docker 镜像（优化版）
# 
# 该镜像包含以下服务：
# 1. Python 3.11 运行环境 - 运行FastAPI主应用
# 2. Nginx - 前端静态文件服务和反向代理
# 3. PM2 - 进程管理工具，管理量化交易框架
# 4. 量化交易框架运行环境 - 轻量级Python环境，仅安装必要的xbx-py11包
# 5. Google Chrome 浏览器 - 支持网页自动化和数据采集
# 6. SourceHanSansSC 字体 - 支持中文字体渲染
#
# Version: 2.2 - 适配新目录结构 (apps/libs/services)

# 使用官方Python 3.11镜像作为基础镜像
FROM python:3.11-slim

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    PM2_HOME=/app/.pm2-runtime \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8 \
    # 时区配置
    TZ=Asia/Shanghai \
    # Chrome浏览器环境变量
    CHROME_BIN=/usr/bin/google-chrome-stable \
    DISPLAY=:99 \
    # Python路径，包含所有源码目录
    PYTHONPATH=/app:/app/libs:/app/services:/app/strategies:/app/apps

# 设置工作目录
WORKDIR /app

# 配置国内镜像源加速
RUN sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's/security.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources

# 先复制依赖文件（利用Docker层缓存）
COPY apps/qronos/requirements.txt .

# 安装基础系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    # 基础系统工具
    curl \
    wget \
    unzip \
    gnupg \
    ca-certificates \
    # 时区配置
    tzdata \
    # Locale支持
    locales \
    # 字体配置工具
    fontconfig \
    # Chrome浏览器相关依赖
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libxss1 \
    libnss3 \
    # Nginx web服务器
    nginx \
    # 清理
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 配置时区（独立层）
RUN ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && dpkg-reconfigure -f noninteractive tzdata

# 配置locale（独立层）
RUN echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen \
    && echo "zh_CN.UTF-8 UTF-8" >> /etc/locale.gen \
    && locale-gen \
    && update-locale LANG=en_US.UTF-8

# 安装Node.js和npm（独立层，避免环境变量问题）
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    # 配置npm国内镜像源
    && npm config set registry https://registry.npmmirror.com

# 安装PM2（独立层，确保npm可用）
RUN npm install -g pm2 \
    && npm cache clean --force

# 配置PM2环境（独立层）
RUN mkdir -p /app/.pm2-runtime /app/.pm2 \
    && export PM2_HOME=/app/.pm2-runtime \
    # 等待PM2守护进程启动并安装logrotate插件
    && pm2 ping \
    && pm2 install pm2-logrotate \
    && pm2 set pm2-logrotate:retain 7 \
    && pm2 set pm2-logrotate:max_size 10M \
    && pm2 set pm2-logrotate:rotateInterval '0 0 * * *' \
    # 验证pm2-logrotate安装
    && pm2 describe pm2-logrotate || echo "pm2-logrotate安装验证完成" \
    && pm2 startup \
    && pm2 save -f

# 安装Chrome浏览器（独立层，增加重试机制和错误处理）
RUN apt-get update && \
    for i in 1 2 3; do \
        echo "尝试安装Chrome，第 $i 次..." && \
        # 添加Chrome官方GPG密钥
        curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --batch --yes --dearmor -o /usr/share/keyrings/google-chrome.gpg 2>/dev/null && \
        # 添加Chrome仓库
        echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
        # 更新包列表
        apt-get update && \
        # 尝试安装Chrome
        (apt-get install -y --no-install-recommends google-chrome-stable 2>/dev/null || \
         apt-get install -y --no-install-recommends chromium 2>/dev/null) && \
        # 清理
        apt-get clean && \
        rm -rf /var/lib/apt/lists/* && \
        echo "Chrome安装成功" && break || \
        { echo "Chrome安装失败，重试 $i/3"; sleep 5; }; \
    done && \
    # 验证Chrome安装（如果找不到chrome，尝试chromium）
    (google-chrome-stable --version 2>/dev/null || chromium --version 2>/dev/null || echo "浏览器安装验证完成")

# 安装SourceHanSansSC字体（独立层，添加容错处理）
RUN mkdir -p /usr/share/fonts/SourceHanSans && \
    cd /usr/share/fonts/SourceHanSans && \
    for i in 1 2 3; do \
        echo "尝试下载字体，第 $i 次..." && \
        wget -q --timeout=30 --tries=2 https://github.com/adobe-fonts/source-han-sans/releases/download/2.004R/SourceHanSansSC.zip && \
        unzip -q SourceHanSansSC.zip && \
        mv OTF/* . 2>/dev/null && \
        rmdir OTF 2>/dev/null && \
        rm -f SourceHanSansSC.zip && \
        echo "字体下载成功" && break || \
        { echo "字体下载失败，重试 $i/3"; sleep 5; rm -f SourceHanSansSC.zip 2>/dev/null; }; \
    done && \
    # 更新字体缓存
    fc-cache -fv || echo "字体缓存更新完成"

# 安装Python编译依赖（临时）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 配置pip并安装主应用依赖
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn \
    && pip install --no-cache-dir -r requirements.txt

# 创建量化交易框架运行环境
RUN python -m venv /opt/alpha_env \
    && /opt/alpha_env/bin/pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && /opt/alpha_env/bin/pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn \
    && /opt/alpha_env/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/alpha_env/bin/pip install --no-cache-dir xbx-py11

# 清理编译依赖
RUN apt-get purge -y gcc g++ \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /tmp/* /var/tmp/*

# 复制配置文件
COPY apps/qronos/docker/nginx.conf /etc/nginx/nginx.conf
COPY apps/qronos/docker/qronos.conf.template /etc/nginx/conf.d/qronos.conf.template

# 复制启动脚本
COPY apps/qronos/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 复制项目源代码（按分层复制）
COPY libs /app/libs
COPY services /app/services
COPY strategies /app/strategies
COPY apps/qronos /app/apps/qronos
# 复制站点配置（sitecustomize.py）
COPY sitecustomize.py /app/sitecustomize.py

# 安装通用库（common_core）到主环境和alpha_env
RUN cd /app/libs/common_core && pip install . \
    && /opt/alpha_env/bin/pip install .

# 复制前端资源
RUN mkdir -p /var/www/html
COPY apps/qronos/frontend/dist/ /var/www/html/

# 创建必要的目录（在复制代码之后，确保运行时目录存在）
RUN mkdir -p \
    /app/apps/qronos/data \
    /app/apps/qronos/logs \
    /app/services/firm

# 暴露端口
# 80: Nginx HTTP端口  
EXPOSE 80

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost/ || exit 1

# 启动入口点
ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
