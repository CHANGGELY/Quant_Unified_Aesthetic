# 全面架构升级与异步化改造计划

## 1. 核心架构重构 (The Core)
目前项目存在严重的“代码复制”现象，我们将创建一个统一的核心库，消除冗余，为 SOTA 架构打下基础。

*   **创建 `Quant_Unified/common_core` 目录**：
    *   `exchange/`: 统一存放交易所客户端（含同步与异步版本）。
    *   `backtest/`: 统一存放回测引擎（Simulator, Equity 等）。
    *   `utils/`: 统一存放工具函数。

## 2. 引入异步并发 (AsyncIO) - 速度提升关键
目前的行情获取是同步阻塞的，效率较低。我们将引入异步并发，将数据获取速度提升 10-50 倍。

*   **实现 `AsyncBinanceClient`**：
    *   基于 `ccxt.async_support` 或 `aiohttp`。
    *   实现 `fetch_candle_data_async` 等高频方法。
*   **改造 `data_job/kline.py`**：
    *   将原有的多线程（伪并发）改为 `asyncio` 协程（真并发）。
    *   实现秒级获取全市场 K 线。

## 3. 数据存储优化 (Data Layer)
*   **Parquet 格式支持**：
    *   在下载脚本中增加 Parquet 格式存储（比 CSV 快且小）。
    *   *注：为了兼容现有回测代码，初期将保持 CSV 输出，但架构上预留 Parquet 接口。*

## 4. 实施步骤
1.  **环境准备**: 检查并安装 `ccxt`, `aiohttp`, `pandas`, `numba` 等依赖。
2.  **核心库迁移**: 将 `firm/backtest_core` 和 `binance` 客户端迁移至 `common_core`。
3.  **异步客户端开发**: 编写新的异步交易客户端。
4.  **数据脚本升级**: 修改 `kline.py` 使用异步客户端。
5.  **验证**: 运行数据下载脚本，对比速度。

此方案将彻底解决“拼装车”问题，将其升级为模块化、高性能的工业级量化系统。