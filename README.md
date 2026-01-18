# 🌌 Quant_Unified Aesthetic

> **全栈量化交易统一平台**：集高频采集、多策略引擎与 Apple 级审美 UI 于一体的 SOTA 量化解决方案。

---

## 💎 项目愿景 (Vision)
本项目致力于打破量化开发的沉闷感，将**顶级全栈架构 (Architect)**与**极致交互审美 (Aesthetic)**完美结合。它不仅是一个交易工具，更是一个充满设计感的量化艺术品。

## 🚀 核心特性 (Key Features)

### 1. 📡 高频数据采集 (Data Acquisition)
- **实时深度订阅**：基于 WebSocket 的异步高频采集系统，支持自定义 `DEPTH_LEVEL`（当前默认 20 档）。
- **历史补全**：自动补全币安官方历史成交与 K 线数据。
- **极速存储**：采用高性能 Parquet 格式，专为海量行情数据优化。

### 2. 🧠 多策略引擎 (Strategy Warehouse)
- **二号网格策略**：成熟的实盘级网格引擎，支持动态参数调整。
- **四号做市策略**：基于 Nautilus Trader 深度集成的做市逻辑。
- **五号预测策略**：引入机器学习推理，实现价格波动的提前感知。
- **七号 VWAP 策略**：基于成交量加权平均价格的高级算法交易。

### 3. 🎨 Qronos 管理后台 (Premium UI)
- **极致审美**：遵循 Apple 设计规范，采用毛玻璃效果 (Glassmorphism) 与平滑动画。
- **技术栈**：Vue 3 + TypeScript + Vite + FastAPI。
- **多端自适应**：无论是 4K 显示器还是移动端，均能提供丝滑的监控体验。

## 📂 项目结构 (Structure)

```text
.
├── Quant_Unified/          # 核心代码库
│   ├── 应用/qronos/        # Qronos 管理后台 (Web + API)
│   ├── 策略仓库/           # 包含网格、做市、预测等 7+ 种策略
│   ├── 服务/               # 数据采集、清洗、历史下载服务
│   ├── 基础库/             # 核心公共组件 (风控、工具类)
│   └── config.py          # 全局统一配置文件 (DEPTH_LEVEL 等)
├── 数据/历史行情中心/     # 统一历史行情数据存放处
├── 数据/模型中心/         # 训练模型与推理产物
├── 输出/                  # 回测报告与可视化产物
├── 文档/                  # 规划文档与资料
├── 工具/                  # 临时工具脚本
├── 归档/                  # 历史项目与旧版本
├── third_party/           # 外部依赖源码（ASCII 路径便于工具链）
├── miniforge/             # 内置轻量级环境管理
└── nautilus_trader/       # 高性能回测与实盘核心集成
```

## 🧩 统一策略架构（最重要）
我们把整个系统统一成“脑子 + 执行器”两段式：
- **策略（脑子）**：只负责决策，输出“我想挂哪些单 / 我想持什么仓位 / 我想分配哪些权重”
- **执行器（手脚）**：只负责执行，回测里做撮合（用 K 线开高低收来判断是否成交），实盘里下真实订单，并做爆仓（保证金不够）检测

这样做的好处是：**同一份策略逻辑**可以同时跑回测与实盘，避免“回测一套、实盘一套”导致结果完全对不上。

## 🛠️ 快速开始 (Quick Start)

### 1. 环境配置
项目内置了 `miniforge` 环境，建议使用 Python 3.12+。
```bash
# 激活环境
source miniforge/bin/activate
```

### 2. 全局配置
修改 `Quant_Unified/config.py` 即可统一控制全系统的深度档位：
```python
DEPTH_LEVEL = 20  # 支持 5, 10, 20, 50, 100
```

### 3. 统一测试入口（CI 同款）
```bash
python3 -X utf8 Quant_Unified/测试用例/运行CI测试.py
```

### 4. 策略接口版回测入口（推荐）
```bash
# 3号对冲策略（接口版：对冲撮合执行器）
python3 -X utf8 Quant_Unified/策略仓库/三号对冲策略/backtest_interface.py --no-chart --limit 5000

# 4号做市策略（接口版：对冲撮合执行器）
python3 -X utf8 "Quant_Unified/策略仓库/4 号做市策略/backtest_interface.py" --no-chart --limit 5000

# 1号择时策略（接口版：脑子输出权重表 + 组合调仓执行器）
python3 -X utf8 Quant_Unified/策略仓库/一号择时策略/select-coin-feat-long_short_compose/backtest_interface.py --no-chart
```

### 5. 启动管理后台
```bash
# 后端启动
cd Quant_Unified/应用/qronos && python main.py
# 前端开发模式
npm run dev
```

## 📜 编码规范
- **中文化编程**：为了降低认知负荷，核心业务逻辑、函数名、变量名优先使用中文。
- **错误自愈**：全系统覆盖完善的异常拦截与自动化恢复机制。
- **SOTA 级代码**：拒绝任何过时的实现，代码风格对标业界最高标准。

---

**Built with ❤️ for High-School Quant Enthusiasts.**
