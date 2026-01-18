I will create a new Python script named `run_strategy.py` in the root directory `f:\量化币圈\邢不行研究小组第39期：1号择时策略小组-2025\select-coin-25年终版\`.

This script will serve as the "backtest rotation tool" you requested. It will:
1.  **Scan the `strategy/` folder**: Automatically list all available strategy files (e.g., `中性策略4.py`).
2.  **Interactive Selection**: Allow you to input the name (or part of the name) of the strategy file you want to run.
3.  **Dynamic Loading**: Load the selected strategy file and inject it as the system configuration, effectively replacing the default `config.py`.
4.  **Execute Backtest**: Run the standard backtest pipeline (`prepare_data`, `calc_factors`, `select_coins`, `simulate_performance`) using the configuration from your selected strategy file.

This achieves your goal of running a specific strategy just by providing its filename, without modifying the main `backtest.py` or manually overwriting `config.py`.

### Implementation Steps:
1.  Create `run_strategy.py` with the following logic:
    *   List `.py` files in `strategy/`.
    *   Prompt user for input.
    *   Use `importlib` to load the chosen file.
    *   Monkeypatch `sys.modules['config']` to point to this loaded strategy module.
    *   Import backtest modules (`core`, `program`) *after* the configuration is injected.
    *   Run the backtest functions.

No changes are required to your existing `backtest.py` or `config.py` files.
