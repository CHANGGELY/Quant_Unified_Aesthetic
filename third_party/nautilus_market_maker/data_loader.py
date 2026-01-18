"""
Data Loader (数据加载器)
------------------------
这里进行了一次“魔改”：
为了让 FeatureEngine 能算出来复杂的 OBI 指标，
我们在 QuoteTick 对象上悄悄挂载了 `depth` 属性，
包含了完整的 5 档买卖单数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd

from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.model.identifiers import InstrumentId, TradeId

try:
    from nautilus_trader.model.enums import AggressorSide
except Exception:
    AggressorSide = None


def to_ns_timestamp(series: pd.Series, unit: str) -> np.ndarray:
    if np.issubdtype(series.dtype, np.integer):
        return pd.to_datetime(series, unit=unit, utc=True).view("int64")
    return pd.to_datetime(series, utc=True).view("int64")



# 全局缓存，用于存放无法挂载到 QuoteTick 上的深度快照
DEPTH_SNAPSHOT_CACHE = {}

def load_depth5_parquet(
    path: str,
    instrument_id: InstrumentId,
    timestamp_unit: str = "ms",
    instrument=None,
) -> List[QuoteTick]:
    print(f"正在加载深度数据: {path} ...")
    df = pd.read_parquet(path)
    
    # Smart Timestamp Loading
    ts_values = df["timestamp"].values.astype(np.float64)
    if np.nanmax(ts_values) < 2e10: # Seconds
        ts_ns = (ts_values * 1e9).astype(np.int64)
    elif np.nanmax(ts_values) < 2e13: # Milliseconds
        ts_ns = (ts_values * 1e6).astype(np.int64)
    elif np.nanmax(ts_values) < 2e16: # Microseconds
        ts_ns = (ts_values * 1e3).astype(np.int64)
    else: # Nanoseconds
        ts_ns = ts_values.astype(np.int64)

    # 提取所有档位的数据，用于挂载
    # 假设列名是 bid1_p, bid1_q ... bid5_p, bid5_q
    # 构造 (N, 5) 的数组
    bids_p = np.stack([df[f"bid{i}_p"].values for i in range(1, 6)], axis=1)
    bids_q = np.stack([df[f"bid{i}_q"].values for i in range(1, 6)], axis=1)
    asks_p = np.stack([df[f"ask{i}_p"].values for i in range(1, 6)], axis=1)
    asks_q = np.stack([df[f"ask{i}_q"].values for i in range(1, 6)], axis=1)

    # 第1档用于 QuoteTick 标准字段
    bid1_p = bids_p[:, 0]
    bid1_q = bids_q[:, 0]
    ask1_p = asks_p[:, 0]
    ask1_q = asks_q[:, 0]

    ticks: List[QuoteTick] = []
    
    # 清空缓存
    DEPTH_SNAPSHOT_CACHE.clear()
    
    for i, ts in enumerate(ts_ns):
        # 1. 构造深度快照 (用于特征计算)
        # 格式: {'bids': [[p,q], [p,q]...], 'asks': ...}
        snapshot = {
            'bids': np.column_stack((bids_p[i], bids_q[i])),
            'asks': np.column_stack((asks_p[i], asks_q[i]))
        }
        
        # 2. 构造标准 Tick
        bp = bid1_p[i]
        ap = ask1_p[i]
        bs = bid1_q[i]
        as_ = ask1_q[i]
        
        if instrument:
            try:
                bp = instrument.make_price(bp)
                ap = instrument.make_price(ap)
                bs = instrument.make_qty(bs)
                as_ = instrument.make_qty(as_)
            except:
                pass

        tick = QuoteTick(
            instrument_id=instrument_id,
            bid_price=bp,
            bid_size=bs, # 只放第一档量
            ask_price=ap,
            ask_size=as_,
            ts_event=int(ts),
            ts_init=int(ts),
        )
        
        # 将快照存入全局缓存
        # 注意: ts_event 可能会重复? 如果重复，后一个覆盖前一个，通常 backtest 精度够高不会重，或者 we prefer last
        DEPTH_SNAPSHOT_CACHE[tick.ts_event] = snapshot
        
        ticks.append(tick)
        
    print(f"深度数据加载完毕，共 {len(ticks)} 条。")
    return ticks


def load_trades_parquet(
    path: str,
    instrument_id: InstrumentId,
    timestamp_unit: str = "ms",
    instrument=None,
) -> List[TradeTick]:
    print(f"正在加载成交数据: {path} ...")
    df = pd.read_parquet(path)
    # Smart Timestamp Loading
    # Check if timestamp is likely seconds (float or int) and scale to nanoseconds
    ts_values = df["timestamp"].values.astype(np.float64)
    # Heuristic: 2025 in seconds is ~1.75e9, in ns is ~1.75e18
    if np.nanmax(ts_values) < 2e10: # Seconds
        ts_ns = (ts_values * 1e9).astype(np.int64)
    elif np.nanmax(ts_values) < 2e13: # Milliseconds
        ts_ns = (ts_values * 1e6).astype(np.int64)
    elif np.nanmax(ts_values) < 2e16: # Microseconds
        ts_ns = (ts_values * 1e3).astype(np.int64)
    else: # Nanoseconds
        ts_ns = ts_values.astype(np.int64)
    
    # Validation
    if len(ts_ns) > 0 and ts_ns[0] < 1e18:
        print(f"Warning: Timestamp appears suspiciously small: {ts_ns[0]} (ns?). Expected ~1.7e18 for 2025.")

    prices = df["price"].values
    sizes = df["qty"].values
    is_buyer_maker = df["is_buyer_maker"].values

    ticks: List[TradeTick] = []
    for i, ts in enumerate(ts_ns):
        price = prices[i]
        size = sizes[i]
        
        if instrument:
            try:
                price = instrument.make_price(price)
                size = instrument.make_qty(size)
            except:
                pass

        aggressor = None
        if AggressorSide:
            aggressor = AggressorSide.SELLER if is_buyer_maker[i] else AggressorSide.BUYER

        trade_kwargs = dict(
            instrument_id=instrument_id,
            price=price,
            size=size,
            aggressor_side=aggressor,
            trade_id=TradeId(str(i)),
            ts_event=int(ts),
            ts_init=int(ts),
        )

        ticks.append(TradeTick(**trade_kwargs))
            
    return ticks


def merge_tick_streams(quotes, trades):
    # 简单合并
    q_iter = iter(quotes)
    t_iter = iter(trades)
    q = next(q_iter, None)
    t = next(t_iter, None)

    while q is not None or t is not None:
        if t is None:
            yield q
            q = next(q_iter, None)
        elif q is None:
            yield t
            t = next(t_iter, None)
        elif q.ts_event <= t.ts_event:
            yield q
            q = next(q_iter, None)
        else:
            yield t
            t = next(t_iter, None)
