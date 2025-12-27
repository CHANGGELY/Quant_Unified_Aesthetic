# Execution Plan: Backtest Framework Fusion & Localization

**Track ID**: `backtest_fusion_20251226`
**Objective**: Establish `Quant_Unified/基础库/通用选币回测框架` by merging `select-coin-25年终版` features with `Quant_Unified`'s Long/Short capabilities, and applying deep localization (Chinese).

## Phase 1: Structure & Analysis
- [x] **Create Directory Structure**:
    - `Quant_Unified/基础库/通用选币回测框架/`
    - Subdirs: `核心`, `因子库`, `工具箱`, `流程`, `数据`
- [x] **Analyze Core Logic**:
    - Diff `select-coin-25年终版/core/simulator.py` vs `Quant_Unified/策略仓库/一号择时策略/select-coin-feat-long_short_compose/core/simulator.py` (or best candidate) to identify Long/Short logic to preserve.

## Phase 2: Core Module Fusion (核心融合)
- [x] **Migrate Core**:
    - Copy merged logic to `Quant_Unified/基础库/通用选币回测框架/核心/`.
- [x] **Localization (Code & Filenames)**:
    - Rename `simulator.py` -> `回测引擎.py`.
    - Rename `equity.py` -> `资金曲线.py`.
    - Refactor class names (e.g., `Simulator` -> `回测引擎`), methods, and variables to Chinese.
    - Translate comments.

## Phase 3: Factor Library Migration (因子库迁移)
- [x] **Migrate Factors**:
    - Copy all factors from `select-coin-25年终版/factors/` to `Quant_Unified/基础库/通用选币回测框架/因子库/`.
    - Check for unique factors in `Quant_Unified` and merge.
- [x] **Localization**:
    - Rename factor files to Chinese (e.g., `ma.py` -> `移动平均.py` where applicable, or keep standard technical names if preferred but wrap in Chinese functions).
    - Ensure function names are Chinese (e.g., `def 计算_MA():`).

## Phase 4: Tools Migration (工具箱迁移)
- [x] **Migrate Tools**:
    - Copy `select-coin-25年终版/tools/` to `Quant_Unified/基础库/通用选币回测框架/工具箱/`.
- [x] **Fix Imports**:
    - Update all import paths in tools to point to `Quant_Unified.基础库.通用选币回测框架...`.
- [ ] **Verify Streamlit**:
    - Ensure `app.py` or dashboard scripts run correctly from the new location.

## Phase 5: Workflow Integration (流程整合)
- [x] **Migrate Program**:
    - Copy `select-coin-25年终版/program/` to `Quant_Unified/基础库/通用选币回测框架/流程/`.
- [x] **Localization**:
    - Rename main scripts (e.g., `01_run.py` -> `01_启动选币.py`).
    - Update logic to call the new localized Core and Factors.

## Phase 6: Final Verification (验收)
- [x] **Test Run**:
    - Create a sample run script in `Quant_Unified/基础库/通用选币回测框架/示例.py`.
    - Verify Step 1-4 (Data, Factors, Select, Backtest) runs without error.
- [x] **Check Equity Curve**:
    - Ensure output plots are generated.
- [x] **Tool Check**:
    - Launch Streamlit dashboard and load results.
