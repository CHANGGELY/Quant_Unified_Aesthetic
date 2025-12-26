---
alwaysApply: false
description: 项目结构、技术栈与命名规范
---
项目结构规范：
- 根目录仅放全局入口与配置：`README.md`、`requirements.txt`、`apps/`、`libs/`、`services/`、`strategies/`、`tests/`。
- 新策略统一放在 `strategies/` 下，每个策略独立目录，包含 `README.md`、`config*.py`、`backtest.py`、`real_trading.py`、`program/`、`tests/` 等。
- `libs/` 放通用组件与工具（日志、计算、网络封装）；策略复用代码先下沉到 `libs/`。
- `logs/`、`cache/`、`memory/`、`data/` 为运行时产物，默认不进入版本控制。
- 目录结构改动需同步更新相关 `README.md`。
策略目录模板（必备文件清单）：
- `README.md`：策略说明、参数含义、运行方式（回测/实盘）。
- `config_live.py`：实盘参数与账户相关配置（不含密钥明文）。
- `config_backtest.py`：回测参数与数据路径配置（不含密钥）。
- `backtest.py`：回测入口，支持批量/区间回放。
- `real_trading.py`：实盘入口，包含风控与断线恢复逻辑。
- `program/`：策略核心逻辑与执行流程，拆分为可测试模块。
- `tests/`：`test_*.py` 测试用例（核心计算与策略边界条件）。
- 可选：`common/` 或 `core/` 仅放策略内复用组件；若跨策略复用则迁移到 `libs/`。
技术栈限制：
- 主要语言为 Python（保持与现有版本一致），新增依赖需补充 `requirements.txt` 并说明用途。
- 交易所接口优先使用 `ccxt`；HTTP/异步使用 `aiohttp`/`asyncio`；服务端接口使用 `FastAPI`/`uvicorn`（如已有服务）。
- 数据处理与回测优先使用 `pandas`/`numpy`；绘图使用 `matplotlib`/`plotly`（如已有依赖）。
- 避免引入与现有功能重叠的新框架；必要时先评估并记录原因。
代码风格与测试规范：
- 遵循 PEP 8 与现有代码风格，避免引入明显风格漂移。
- 对外接口与关键逻辑函数补充类型注解；复杂对象优先写明输入/输出结构。
- 关键流程（下单、风控、资金计算）必须有单元测试；外部依赖用 mock 或沙盒环境。
- 测试应可在本地离线运行，禁止测试直接调用真实交易接口。
- 若引入 lint/format 工具，需提供统一配置文件并在 `README.md` 说明用法。
命名规则：
- Python 文件、函数、变量使用 `snake_case`；类使用 `CapWords`；常量使用 `UPPER_SNAKE_CASE`。
- 测试文件以 `test_*.py` 命名；脚本入口保持 `if __name__ == "__main__":`。
- 配置文件使用 `config_*.py`/`config*.yaml`，语义清晰如 `config_live.py`、`config_backtest.py`。
- 策略目录命名保持与现有一致（中文序号+策略名）；新增策略需附 `README.md`。
- 日志/输出文件使用可排序时间戳或日期前缀（`YYYYMMDD`），避免特殊字符。
实盘/回测配置管理约束：
- 实盘与回测配置分离维护，字段命名保持一致，避免同名字段语义不一致。
- 任何密钥、账户信息仅从环境变量或 `.env` 读取，禁止硬编码入库。
- 启动时记录配置快照（脱敏后）到日志，便于复盘与问题定位。
