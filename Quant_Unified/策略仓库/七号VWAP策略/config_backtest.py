# -*- coding: utf-8 -*-
"""
7号 VWAP 策略 - 回测配置（统一架构版）

这个文件是干嘛的？
    给 “七号VWAP策略（接口回测）” 提供一套干净的配置入口。

说明（用人话）：
    - VWAP：成交量加权平均价，你可以把它理解成“市场这段时间的平均成交成本”
    - 策略逻辑：收盘价在 VWAP 上方 -> 偏多；在下方 -> 偏空
    - 为了避免“看未来”：信号会延迟 1 根 K 线执行（上一根的信号，下一根才下单）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _默认数据文件路径() -> Path:
    v = os.environ.get("VWAP7_DATA_PATH", "").strip()
    if v:
        return Path(v)

    try:
        from common_core.data_center import 生成分钟K线文件名, 获取分钟K线H5文件

        文件名 = 生成分钟K线文件名("ETHUSDT", 开始日期="2019-11-01", 结束日期="2025-06-15", 带table后缀=True)
        return 获取分钟K线H5文件(文件名)
    except Exception:
        repo_root = Path(__file__).resolve().parents[3]
        return repo_root / "数据" / "历史行情中心" / "分钟K线" / "ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5"


@dataclass(frozen=True)
class VwapStrategy7Config:
    symbol: str = "ETHUSDT"

    # 数据（真实 HDF5）
    data_path: Path = field(default_factory=_默认数据文件路径)
    h5_dataset: str = "klines/table"
    time_col: str = "candle_begin_time_GMT8"

    start_date: str = "2021-01-01"
    end_date: str = "2025-06-15"

    # 指标参数
    vwap_window: int = 1196

    # 交易成本（单边）
    fee_rate: float = 0.0
    slippage_rate: float = 0.0001

    # 仓位与执行器
    initial_capital: float = 10_000.0
    leverage: float = 1.0
    qty_step: float = 0.001
    min_order_notional: float = 5.0

    # 爆仓阈值：保证金率 < 维持保证金率 -> 爆仓
    min_margin_rate: float = 0.005

