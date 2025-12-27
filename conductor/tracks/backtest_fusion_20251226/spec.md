# Track Specification: 回测框架融合与深度中文化 (Backtest Framework Fusion & Localization)

## 1. 概述 (Overview)
本任务旨在将 `select-coin-25年终版` (上游版本) 的优势特性，深度融合到 `Quant_Unified` 项目中。目标是创建一个位于 `Quant_Unified/基础库/通用选币回测框架` 的全新、独立、功能完备且**全中文化**的回测系统。该系统将作为未来所有选币策略的通用底座。

## 2. 核心目标 (Core Goals)
1.  **特性移植 (Feature Backport)**: 将 `25年终版` 中更丰富的 `factors` (80+因子) 和强大的 `tools` (可视化工具) 完整迁移过来。
2.  **核心升级 (Core Upgrade)**: 对比合并 `core` 模块，保留 `Quant_Unified` 特有的长短仓支持，同时吸收 `25年终版` 的潜在性能优化。
3.  **深度中文化 (Deep Localization)**:
    *   目录名、文件名全部中文。
    *   核心类名、函数名、关键变量名全部中文（如 `def 计算均线(数据):`）
    *   代码注释全部中文。
4.  **架构独立 (Architecture)**: 新框架不依赖单一策略，而是作为 `基础库` 的一部分，供所有策略调用。

## 3. 功能需求 (Functional Requirements)

### 3.1 目录结构重构 (Directory Restructure)
目标路径: `Quant_Unified/基础库/通用选币回测框架/`
建议结构:
*   `核心/` (原 core)
    *   `模型/` (原 models)
    *   `回测引擎.py` (原 simulator.py)
    *   `资金曲线.py` (原 equity.py)
*   `因子库/` (原 factors, 合并两边因子)
*   `工具箱/` (原 tools, 完整迁移)
*   `流程/` (原 program, 选币主流程)
*   `数据/` (原 data)

### 3.2 模块融合 (Module Fusion)
*   **因子库**: 合并 `25年终版` 和 `Quant_Unified` 的因子文件，去重并统一命名风格。
*   **工具箱**: 迁移所有 Streamlit 可视化工具，确保路径引用修正为新结构。
*   **长短仓兼容**: 确保合并后的 `核心/回测引擎.py` 依然支持 Long/Short 双向交易（这是原 `Quant_Unified` 的特性）。

## 4. 验收标准 (Acceptance Criteria)
1.  **独立运行**: 新框架下的示例策略能跑通 Step1-4 全流程。
2.  **工具可用**: `工具箱/` 下的 Streamlit 可视化工具（如“参数平原图”）能正常启动并读取数据。
3.  **中文达标**: 核心代码阅读无障碍，函数名和变量名符合中文直觉。
4.  **无损合并**: 原有的长短仓策略逻辑在新框架下依然有效。

## 5. 超出范围 (Out of Scope)
*   对接实盘交易接口 (本次仅专注回测与选币)。
*   重写非 Python 语言的底层库。
