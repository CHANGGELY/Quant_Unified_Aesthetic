## 本系统著作由[《邢不行-量化小讲堂》](https://www.quantclass.cn/home)领导，专门针对分享会成员定制化服务而来

## 本系统完全开源，请在使用系统前仔细审计框架代码

## 本系统不包含任何隐藏后门程序

## 本系统所有数据缓存在部署电脑的磁盘上

## 本系统不会传输任何实盘相关信息给彩虹官方或其他机构

## 本系统持续更新中···

## 本系统每次更新版本，会更新`code.txt`内容，使用系统需要重新验证

## 如果已确认以上信息，请在系统中输入代码目录下`code.txt`文本中内容进行验证，表明你已知晓上述内容

---

## 📜 License / 许可证

**English:**  
This project is licensed under the **MIT Non-Commercial Attribution License (MIT-NC-Attr)**.  
- ✅ Free for personal, educational, and research use.  
- 🚫 Commercial use is prohibited without prior written permission.  
- 📌 Forks or derivative works must include clear attribution and a link to the original repository.  

See [LICENSE](./LICENSE) for full details.

**中文说明:**  
本项目采用 **MIT 非商业署名许可证 (MIT-NC-Attr)**。  
- ✅ 允许个人、教育、研究等非商业用途免费使用。  
- 🚫 未经书面许可，禁止任何商业用途。  
- 📌 Fork 或衍生项目必须清晰标注原作者及项目地址，并附上原仓库链接。  

完整条款请查看 [LICENSE](./LICENSE)。

---

# Qronos 量化交易框架管理系统

> 🚀 专业的量化交易框架管理平台，支持多架构Docker部署

## 📋 项目概述

Qronos 是一个现代化的量化交易框架管理系统，提供以下核心功能：

- 🔒 **安全认证**：Google Authenticator 2FA + JWT Token 双重认证
- 📦 **框架管理**：自动下载、部署和管理量化交易框架
- 🎛️ **配置管理**：可视化配置数据中心和策略参数
- 📊 **状态监控**：实时监控框架运行状态和日志
- 🐳 **容器化部署**：支持 Docker 多架构部署（AMD64/ARM64）

## 🛠️ 技术栈

- **后端**: Python 3.11 + FastAPI + SQLAlchemy
- **前端**: Vue.js + Element-UI
- **数据库**: SQLite
- **容器**: Docker + Nginx + PM2
- **认证**: Google Authenticator + JWT

## 🚀 快速开始

### 1. 环境要求

- Python 3.11+
- Docker Desktop (支持 Buildx)
- Node.js 20+ (用于前端构建)

### 2. 本地开发

```bash
# 克隆项目
git clone <repository-url>
cd qronos

# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
python main.py
```

## 🐳 Docker 构建与发布

### 构建脚本说明

项目提供两个主要的构建脚本：

| 脚本 | 用途 | 特点 |
|------|------|------|
| `build-multiarch-fast.sh` | 高性能构建 | 多级缓存、自动优化、故障恢复 |

### 构建命令

#### 快速构建（推荐）

```bash
# 标准模式 - 平衡速度和稳定性
./scripts/build-multiarch-fast.sh [用户名] [版本号]

# 示例
./scripts/build-multiarch-fast.sh myuser v1.0.0
```

#### 高性能构建

```bash
# 积极缓存模式 - 最快构建速度
./scripts/build-multiarch-fast.sh myuser v1.0.0 aggressive

# 离线模式 - 无网络依赖
./scripts/build-multiarch-fast.sh myuser v1.0.0 offline
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `用户名` | Docker Hub 用户名 | `xbxtempleton` |
| `版本号` | 镜像版本标签 | 时间戳 |
| `缓存模式` | `normal`/`aggressive`/`offline` | `normal` |
| `Dockerfile` | 指定 Dockerfile 文件 | `Dockerfile` |

## 📋 完整发布流程

### 1. 准备阶段

```bash
# 检查Docker环境
docker --version
docker buildx version

# 登录Docker Hub
docker login

# 检查项目状态
git status
```

### 2. 构建镜像

```bash
# 快速构建（推荐）
./scripts/build-multiarch-fast.sh myuser v1.0.0 aggressive
```

### 3. 验证构建

```bash
# 检查镜像
docker manifest inspect myuser/qronos-trading-framework:v1.0.0

# 本地测试
docker run --rm -p 8080:80 myuser/qronos-trading-framework:v1.0.0
```

### 4. 生产部署

```bash
# 一键部署脚本（自动安装Docker + 部署框架）
./scripts/deploy-qronos.sh

# 或指定参数
./scripts/deploy-qronos.sh myuser/qronos v1.0.0 qronos-app --docker-mirror china

# 自动配置虚拟内存（推荐用于小内存服务器）
./scripts/deploy-qronos.sh --auto-setup-swap

# 跳过内存检查
./scripts/deploy-qronos.sh --skip-swap-check
```

### 5. 内存配置优化

对于内存较小的服务器（如2核4G），建议配置虚拟内存来避免量化框架运行时的内存溢出：

```bash
# 自动配置虚拟内存（推荐）
./scripts/deploy-qronos.sh --auto-setup-swap

# 或通过部署脚本自动配置
./scripts/deploy-qronos.sh --auto-setup-swap

# 检查内存状态
free -h
```

**内存配置建议：**
- 2GB物理内存：建议配置6GB虚拟内存
- 4GB物理内存：建议配置4GB虚拟内存  
- 8GB以上：通常无需额外虚拟内存

**注意事项：**
- 虚拟内存需要在宿主机上配置，不是在容器内
- 虚拟内存会占用磁盘空间，确保有足够存储
- 虽然虚拟内存可以缓解内存不足，但会影响性能

## 🔧 构建优化

### macOS 优化建议

1. **Docker Desktop 配置**
   - 内存: 8GB+
   - CPU: 4核+
   - 磁盘: 64GB+

2. **启用实验性功能**
   - VirtioFS 加速目录共享
   - containerd 镜像存储

3. **Apple Silicon (M1/M2) 用户**
   ```bash
   # 自动优化原生架构
   ./scripts/build-multiarch-fast.sh myuser v1.0.0 aggressive auto
   ```

### 性能对比

| 构建方式 | 首次构建 | 增量构建 | 缓存命中率 |
|----------|----------|----------|------------|
| 标准构建 | 15-20分钟 | 8-12分钟 | 30-40% |
| 优化构建 | 8-12分钟 | 3-5分钟 | 60-70% |
| 积极缓存 | 5-8分钟 | 1-3分钟 | 80-90% |

## 🐛 故障排除

### 常见问题

1. **构建失败**
   ```bash
   # 清理缓存重试
   docker builder prune --all
   ```

2. **网络问题**
   ```bash
   # 使用离线模式
   ./scripts/build-multiarch-fast.sh myuser v1.0.0 offline
   ```

3. **权限问题**
   ```bash
   # 检查Docker登录状态
   docker info | grep Username
   
   # 重新登录
   docker login
   ```

4. **内存不足问题** ⭐
   ```bash
   # 检查内存状态
   free -h
   
   # 配置虚拟内存（推荐使用部署脚本）
   ./scripts/deploy-qronos.sh --auto-setup-swap
   
   # 手动配置虚拟内存
   sudo fallocate -l 4G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   
   # 监控内存使用
   docker stats qronos-app
   ```

5. **量化框架内存溢出**
   ```bash
   # 检查容器内存限制
   docker stats <容器名>
   
   # 为容器设置合适的内存限制
   docker run --memory=6g <镜像名>
   
   # 检查框架日志
   docker logs <容器名> | grep -i "memory\|oom"
   
   # 优化框架配置（减少并发数、缓存大小等）
   ```

### 调试技巧

```bash
# 查看构建日志
./scripts/build-multiarch-fast.sh myuser debug > build.log 2>&1

# 单独构建特定架构
docker buildx build --platform linux/amd64 --tag myuser/qronos:amd64 .

# 检查镜像层信息
docker history myuser/qronos-trading-framework:latest

# 查看系统资源使用
htop
iostat -x 1
```

## 📊 项目结构

```
qronos/
├── 📁 config.py              # 配置文件
├── 📁 data/                  # 数据存储目录
├── 📁 db/                    # 数据库模块
├── 📁 docker/                # Docker配置文件
├── 📁 frontend/              # 前端代码
├── 📁 model/                 # 数据模型
├── 📁 scripts/               # 构建和管理脚本
│   ├── 🚀 deploy-qronos.sh  # 一键部署脚本（含内存配置）
├── 📁 service/               # 业务逻辑
├── 📁 utils/                 # 工具模块
├── 🐳 Dockerfile             # 标准Docker文件
├── 🐳 Dockerfile.multiarch   # 多阶段优化版本
├── 🐍 main.py               # 主程序入口
└── 📋 requirements.txt       # Python依赖
```

## 🛠️ 管理工具

部署脚本 `deploy-qronos.sh` 现已集成内存配置和监控功能：

```bash
# 首次部署（自动配置内存）
./scripts/deploy-qronos.sh --auto-setup-swap

# 跳过内存检查
./scripts/deploy-qronos.sh --skip-swap-check

# 查看帮助信息
./scripts/deploy-qronos.sh --help
```

---
