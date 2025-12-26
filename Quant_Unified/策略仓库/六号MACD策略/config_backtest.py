from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_path() -> Path:
    v = os.environ.get("MACD6_DATA_PATH")
    if v:
        return Path(v)
    repo_strat_root = Path(__file__).resolve().parents[1]  # Quant_Unified/策略仓库
    return repo_strat_root / "二号网格策略" / "data_center" / "ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5"


@dataclass(frozen=True)
class MacdStrategy6Config:
    symbol: str = "ETHUSDT"

    # 数据源（HDF5，需 h5py + hdf5plugin）
    data_path: Path = field(default_factory=_default_data_path)
    h5_dataset: str = "klines/table"
    time_col: str = "candle_begin_time_GMT8"  # ns 时间戳

    # MACD 参数
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # 交易成本（单边）
    fee_rate: float = 0.00021  # 0.021%
    slippage_rate: float = 0.0001  # 0.01%

    # 仓位与撮合（单标的近似，执行价=close；qty_step 为下单精度示例）
    initial_capital: float = 10_000.0
    qty_step: float = 0.001
    min_order_notional: float = 5.0

    # 凯利仓位（按“每笔交易的单位名义收益率”估计）
    kelly_window_trades: int = 100
    kelly_min_trades: int = 30
    leverage_init: float = 0.2
    leverage_min: float = 0.1
    leverage_max: float = 1.0
