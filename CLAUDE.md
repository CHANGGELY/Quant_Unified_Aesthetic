# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个名为 **Quant_Unified** 的全栈量化交易统一平台，集高频数据采集、多策略引擎与 Apple 级审美 UI 于一体。项目采用中文化编程以降低认知负荷，用户定位为高中生量化爱好者。

## 常用命令

### 环境配置
```bash
# 激活内置环境
source miniforge/bin/activate

# 安装 Python 依赖
pip install -r Quant_Unified/requirements.txt

# 安装前端依赖
cd Quant_Unified/应用/qronos
npm install
```

### 启动服务

```bash
# 1. 数据采集服务
cd Quant_Unified/服务/数据采集
python 启动采集.py

# 2. Web 管理后台 - 后端
cd Quant_Unified/应用/qronos
python main.py

# 3. Web 管理后台 - 前端开发
cd Quant_Unified/应用/qronos
npm run dev

# 4. Gradio 监控面板
cd Quant_Unified
python app.py
```

### 策略回测

```bash
# 八号香农策略回测
cd Quant_Unified
python -X utf8 策略仓库/八号香农策略/backtest.py

# 其他策略类似，进入对应目录运行 backtest.py
```

### Docker 部署

```bash
# 构建镜像
docker build -t quant-unified .

# 运行容器
docker run -p 7860:7860 quant-unified
```

## 核心架构

### 1. 技术栈

**后端：**
- Python 3.12 + FastAPI（Web API）
- Nautilus Trader（高性能交易框架）
- CCXT（交易所接口）
- WebSockets（实时数据）
- Supabase（云端数据库）
- Pandas/NumPy（数据处理）

**前端：**
- Vue 3 + TypeScript
- Vite（构建工具）
- Tailwind CSS + PrimeVue（UI框架）
- ECharts（数据可视化）

**数据存储：**
- PyArrow/Parquet（高频数据）
- Redis（缓存）
- SQLite（本地数据库）

### 2. 目录结构

```
Quant_Unified/
├── 策略仓库/          # 8个交易策略
│   ├── 二号网格策略/
│   ├── 四号做市策略/
│   ├── 五号预测策略/
│   ├── 七号VWAP策略/
│   └── 八号香农策略/
├── 应用/qronos/       # Web管理后台
├── 服务/              # 后台服务
│   ├── 数据采集/
│   └── firm/
├── 基础库/            # 公共组件
│   ├── common_core/
│   └── 通用选币回测框架/
├── config.py          # 全局配置
└── app.py            # Gradio监控面板
```

### 3. 关键配置

全局配置在 `Quant_Unified/config.py`：
- `DEPTH_LEVEL`：深度图档位（支持 5, 10, 20, 50, 100）
- 修改此值会影响整个数据采集和存储结构

### 4. 策略系统

每个策略目录包含：
- `config_live.py`：实盘配置
- `config_backtest.py`：回测配置
- `backtest.py`：回测脚本
- `real_trading.py`：实盘交易脚本
- `program/`：策略核心逻辑

### 5. 数据流架构

1. **数据采集层**：WebSocket 实时订阅币安深度数据
2. **数据存储层**：Parquet 格式高效存储
3. **策略引擎层**：独立的策略模块，可并行运行
4. **交易执行层**：通过 Nautilus Trader 连接交易所
5. **监控管理层**：Qronos Web 界面统一管理

## 开发规范

### 1. 中文化编程
- 函数名、变量名优先使用中文
- 必须用中文注释解释代码逻辑
- 文件头必须有中文说明

### 2. 代码质量
- 对标业界最高标准（Apple/Google）
- 使用 SOTA 技术栈，避免过时实现
- 完善的异常处理和自动恢复机制
- 严禁使用模拟数据，必须连接真实接口

### 3. 运行要求
- 所有脚本必须显式运行，有实时日志输出
- 使用 `python -X utf8` 确保中文处理无乱码
- 前端 TypeScript 零容忍报错

## 重要提醒

1. **DEPTH_LEVEL 修改影响**：调整深度档位会重新构建数据结构，需谨慎操作
2. **策略独立性**：每个策略都是独立的，可单独开发和测试
3. **实时监控**：通过 Qronos 界面可监控所有策略运行状态
4. **回测系统**：使用向量化操作加速，支持参数优化
5. **环境隔离**：使用内置 miniforge 环境，避免依赖冲突