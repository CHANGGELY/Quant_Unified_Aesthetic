# 实施计划 - Tardis 高频数据与 LightGBM 整合

## 第一阶段：数据工程基础 (Tardis ETL) [checkpoint: 9420e51]
**目标：** 实现基于 Polars 的高性能下载和极致压缩流水线。
- [x] 任务：创建数据处理脚本 `Quant_Unified/策略仓库/五号预测策略/scripts/tardis_etl.py` 9420e51
    - [x] 子任务：实现核心的 `process_and_compress` 函数，包含“浮点转整数”和 Zstd 压缩逻辑。 9420e51
    - [x] 子任务：实现 `get_monthly_first_days` 工具函数和主下载循环。 9420e51
    - [x] 子任务：添加命令行参数支持（CLI），以便手动指定币种和日期范围。 9420e51
- [x] 任务：验证数据完整性 9420e51
    - [x] 子任务：编写测试脚本 `test_compression.py`，压缩一个 CSV 样本并立即解压/还原。 9420e51
    - [x] 子任务：断言验证 `restored_value`（还原值）与 `original_value`（原始值）相等（允许 < 1e-8 的精度误差）。 9420e51
- [x] 任务：Conductor - 用户手册验证 '数据工程基础' (协议见 workflow.md) 9420e51

## 第二阶段：核心基础设施 (L2 重放引擎) [checkpoint: f5e8bff]
**目标：** 在公共核心库中构建通用的 L2 订单簿重放引擎。
- [x] 任务：创建 `Quant_Unified/基础库/common_core/utils/orderbook_replay.py` f5e8bff
    - [x] 子任务：定义 `OrderBook` 类，包含 `bids` 和 `asks` 属性（使用 `SortedDict` 或优化结构）。 f5e8bff
    - [x] 子任务：实现 `apply_delta(side, price_int, amount_int)` 方法，处理增量更新。 f5e8bff
    - [x] 子任务：实现 `get_snapshot(depth=50)` 方法，返回指定深度的快照。 f5e8bff
- [x] 任务：编写重放引擎单元测试 f5e8bff
    - [x] 子任务：创建 `Quant_Unified/基础库/common_core/tests/test_orderbook_replay.py`。 f5e8bff
    - [x] 子任务：测试用例覆盖：“新增价格档位”、“更新现有档位”、“删除档位 (数量为0)”、“快照深度检查”。 f5e8bff
- [x] 任务：Conductor - 用户手册验证 '核心基础设施' (协议见 workflow.md) f5e8bff

## 第三阶段：策略配置与数据适配器 [checkpoint: 57f9e35]
**目标：** 让五号策略支持配置化切换新数据流。
- [x] 任务：更新 `Quant_Unified/策略仓库/五号预测策略/config.py` 57f9e35
    - [x] 子任务：添加全局配置：`DATA_SOURCE` ('kaggle' | 'tardis')，`SAMPLE_INTERVAL_MS` (默认 100)，`PRICE_MULT`，`AMOUNT_MULT`。 57f9e35
- [x] 任务：创建数据适配器 `Quant_Unified/策略仓库/五号预测策略/data_loader_tardis.py` 57f9e35
    - [x] 子任务：实现 Polars LazyFrame 读取器，用于加载压缩后的 Parquet 文件。 57f9e35
    - [x] 子任务：实现一个生成器，对接重放引擎，并按配置的 `SAMPLE_INTERVAL_MS` 产出快照。 57f9e35
    - [x] 子任务：确保输出格式与现有特征提取器的输入格式（DataFrame 行结构）完全一致。 57f9e35
- [x] 任务：Conductor - 用户手册验证 '策略配置与数据适配器' (协议见 workflow.md) 57f9e35

## 第四阶段：模型训练 (LightGBM + 100ms)
**目标：** 升级训练流水线以处理 100ms 级别的高频数据。
- [x] 任务：升级特征提取逻辑
    - [x] 子任务：修改 `Quant_Unified/策略仓库/五号预测策略/train.py` (已通过新建 `train_hft_tardis.py` 实现)，使其支持 Tardis 模式。
- [~] 任务：执行训练与验证
    - [ ] 子任务：使用 BTCUSDT（每月1号数据）运行训练。

## 第五阶段：回测与报告
**目标：** 验证新模型在 ETHUSDT 上的跨币种表现。
- [x] 任务：升级回测引擎
    - [x] 子任务：更新 `Quant_Unified/策略仓库/五号预测策略/backtest.py`（或 `cross_symbol_backtest.py`），使其支持 100ms 步长推进。
- [ ] 任务：运行与分析
    - [ ] 子任务：执行回测：BTC 训练 -> ETH 测试。(等待数据下载完成)
    - [ ] 子任务：生成标准的 HTML/PNG 收益曲线报告。(等待数据下载完成)
