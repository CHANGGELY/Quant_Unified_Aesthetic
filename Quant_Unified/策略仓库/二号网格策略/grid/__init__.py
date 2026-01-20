"""
二号网格策略 / grid 包（旧版回测实现）

你会看到这里有一份“自带撮合逻辑”的旧版回测：
    - `grid/grid_backtest.py` 会读取 `config.yaml`，然后跑一套独立的回测流程。

怎么用？
    如果你只是想快速跑一个最小回测，可以直接：
        python3 -X utf8 Quant_Unified/策略仓库/二号网格策略/grid/grid_backtest.py

推荐路径：
    新一点、结构更清晰的回测方式是：
        - `backtest_interface.py`（策略脑子 + 通用执行器）
        - `backtest.py`（Firm 架构版组合回测）
"""

