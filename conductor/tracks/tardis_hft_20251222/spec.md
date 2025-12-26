# 轨道规格说明书 (Spec)

**轨道名称**: `tardis_hft_20251222`
**类型**: 核心功能增强 / 架构升级

#### 1. 业务目标 (Overview)
将“五号预测策略”从现有的低频（1秒）链路升级为**基于 Tardis 原始增量数据、100ms 采样、LightGBM 驱动的高频预测系统**。核心目标是利用极致压缩的 Parquet 存储方案，配合通用 L2 重放引擎，在不损失精度的情况下大幅提升预测频率和策略表现。

#### 2. 核心任务 (Functional Requirements)
-   **数据工程**:
    -   实现 Tardis 下载/压缩/转换一体化脚本。
    -   采用 **Float to Int** 压缩技术 (Price * 100, Amount * 1000)。
    -   使用 **Polars + Zstd (Level 10)** 实现极致压缩和极速读取。
-   **通用组件开发**:
    -   在 `基础库/common_core/` 开发高性能 **L2 Order Book Replay Engine**。
    -   支持将 `incremental_book_L2` 还原为 50 档深度快照。
-   **策略升级**:
    -   修改 `config.py`，支持 `DATA_SOURCE='tardis'` 和 `SAMPLE_INTERVAL=0.1` 参数。
    -   升级训练脚本，支持 100ms 采样频率下的特征提取与 LightGBM 模型训练。
    -   升级回测脚本，确保与训练口径完全一致。

#### 3. 技术标准 (Non-Functional Requirements)
-   **高性能**: L2 重放必须使用 Python 异步或 Polars 向量化优化，确保处理千万级增量数据不卡顿。
-   **零容忍报错**: 类型定义必须精准（尤其是 Float 转 Int 后的还原计算）。
-   **极致审美**: 回测生成的收益曲线图（Equity Curve）需保持高水准。

#### 4. 验收标准 (Acceptance Criteria)
-   [ ] 成功下载并压缩 BTC/ETH 每月 1 号的数据，Parquet 体积显著小于原始 CSV。
-   [ ] 通用重放引擎能正确还原 50 档盘口（随机抽样验证）。
-   [ ] 模型能在 100ms 频率下稳定训练并产出 `.pkl` 文件。
-   [ ] 回测脚本能跑通全流程并输出可视化报告。
