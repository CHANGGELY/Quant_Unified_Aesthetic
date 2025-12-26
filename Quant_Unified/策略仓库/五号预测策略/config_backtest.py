from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_symbol() -> str:
    return os.environ.get("PREDICT5_SYMBOL", "BTCUSDT")


def _default_data_root() -> Path:
    v = os.environ.get("PREDICT5_DATA_ROOT")
    if v:
        return Path(v)
    return Path(__file__).resolve().parents[2] / "data" / "外部数据" / "Kaggle_L2_1m"


@dataclass(frozen=True)
class PredictStrategy5Config:
    # 数据
    symbol: str = field(default_factory=_default_symbol)
    data_root: Path = field(default_factory=_default_data_root)

    # 标签/预测
    horizons_s: tuple[int, ...] = (5, 10, 20, 30, 60) # 分钟级数据下，这里的含义将变为 "未来 N 个数据点" (即 N 分钟)
    label_threshold: float = 0.00052  # 0.052%
    label_modes: tuple[str, ...] = ("executable", "wmp")  # 5.1 / 5.2

    # 信号阈值（迟滞）
    p_enter: float = 0.55
    p_exit: float = 0.55
    diff_enter: float = 0.0
    diff_exit: float = 0.0

    # 交易成本（单边）
    fee_rate: float = 0.00021  # 0.021%
    slippage_rate: float = 0.0001  # 0.01%

    # 仓位
    initial_capital: float = 10_000.0
    leverage: float = 1.0
    qty_step: float = 0.001  # ETH 合约下单精度（示例）
    min_order_notional: float = 5.0  # USDC 永续最小名义（示例）

    # 训练/校准
    train_frac: float = 0.7
    calib_frac: float = 0.15
    calib_method: str = "sigmoid"  # "sigmoid" | "isotonic"
    random_state: int = 42

    # 数据加载/对齐
    depth_levels: int = 20  # Kaggle 数据有 20 档
    start_date: str | None = None  # "YYYY-MM-DD"
    end_date: str | None = None  # "YYYY-MM-DD"
    max_days: int | None = 30  # 例如 60（取最新 N 天），设为 None 则用全量
    cache_1s: bool = False  # Kaggle 数据已经是分钟级，不需要 1s 缓存逻辑
    prefer_longest_contiguous: bool = True
