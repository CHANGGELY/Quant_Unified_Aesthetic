#!/bin/bash

# 安装 Anaconda
echo "开始安装 Anaconda..."
# 下载 Anaconda 安装脚本
wget https://repo.anaconda.com/archive/Anaconda3-2024.06-1-Linux-x86_64.sh -O ~/anaconda_installer.sh
# 运行安装脚本
bash ~/anaconda_installer.sh -b -p $HOME/anaconda3
# 将 Anaconda 添加到 PATH
echo 'export PATH="$HOME/anaconda3/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
# 验证 Anaconda 安装
conda --version

# 安装 PM2
echo "开始安装 PM2..."
# 安装 Node.js（PM2 依赖 Node.js）
sudo apt update
sudo apt install -y nodejs npm
# 安装 PM2
sudo npm install -g pm2
# 验证 PM2 安装
pm2 --version

# 创建 Python 3.11 的 Alpha 环境
echo "创建 Python 3.11 的 Alpha 环境..."
# 切换进Anaconda3的目录中
cd anaconda3
# 激活base环境
source bin/activate
# 创建新的环境
conda create -n Alpha python=3.11 -y
# 激活环境
conda activate Alpha
# 验证 Python 版本
python --version

# 安装 xbx-py11 库
echo "安装 xbx-py11 库..."
pip install xbx-py11


# 完成
echo "Anaconda、PM2、和Python环境安装完成，且安装了xbx-py11库。"

# 启动新的交互式 shell，保持在虚拟环境中
exec $SHELL
exit
