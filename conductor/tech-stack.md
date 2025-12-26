# Tech Stack

## Programming Languages
*   **Python**: 核心业务逻辑、量化策略执行、异步交易核心。
*   **TypeScript**: Qronos 前端平台开发，确保 UI 类型安全。

## Backend (后端)
*   **FastAPI**: 提供高性能、异步的 REST API。
*   **CCXT**: 连接全球加密货币交易所的标准库。
*   **aiohttp**: 异步网络请求，用于非标准 API 和行情采集。

## Frontend (前端)
*   **React / Next.js**: 构建响应式单页面应用 (SPA)。
*   **Tailwind CSS**: 原子化 CSS，用于快速构建专业的数据看板界面。

## Storage (存储)
*   **SQLite (via aiosqlite)**: 存储轻量级的策略配置、用户状态和交易日志。
*   **HDF5 (via h5py)**: 高效存储 TB 级的历史 K 线和行情数据。

## Engineering (工程)
*   **Asyncio**: 整个系统的异步并发模型。
*   **Venv**: Python 虚拟环境隔离。
