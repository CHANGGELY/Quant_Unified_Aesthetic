# -*- coding: utf-8 -*-
"""
十号隐马尔可夫策略 - 特征工程（把原始K线变成 HMM 可吃的“数字特征”）

核心思想（用人话说）：
    HMM 更擅长吃“变化”而不是吃“绝对值”。
    例如：
        - BTC 价格 100000，DOGE 价格 0.1
        - 你直接喂 close，模型学到的只是“数值大小”，不是真正的涨跌

所以我们把 OHLCV（开高收低成交量成交额）转成更公平的比例/变化量：
    - 1h 对数收益（方向）
    - 振幅（震荡强度）
    - 实体（这根K是涨还是跌）
    - 成交量/成交额的对数变化（活跃度变化）
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class HMM特征结果:
    时间序列: np.ndarray  # datetime64
    特征矩阵: np.ndarray  # shape=(T, D)
    特征名: list[str]


def _安全除法(n: np.ndarray, d: np.ndarray) -> np.ndarray:
    d = np.where(np.abs(d) < 1e-12, np.nan, d)
    out = n / d
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def 计算HMM特征(df: pd.DataFrame) -> HMM特征结果:
    if df is None or df.empty:
        raise ValueError("df 不能为空")

    必需列 = {"candle_begin_time", "open", "high", "low", "close", "volume", "quote_volume"}
    缺失 = 必需列 - set(df.columns)
    if 缺失:
        raise ValueError(f"df 缺少必要列: {sorted(缺失)}")

    df = df.sort_values("candle_begin_time").reset_index(drop=True)

    open_ = df["open"].to_numpy(dtype=np.float64)
    high = df["high"].to_numpy(dtype=np.float64)
    low = df["low"].to_numpy(dtype=np.float64)
    close = df["close"].to_numpy(dtype=np.float64)
    vol = df["volume"].to_numpy(dtype=np.float64)
    qv = df["quote_volume"].to_numpy(dtype=np.float64)

    close_safe = np.where(close <= 0, np.nan, close)
    log_close = np.log(close_safe)
    log_close = pd.Series(log_close).ffill().to_numpy(dtype=np.float64)

    # 1) 方向：对数收益（更稳定）
    ret_1h = np.diff(log_close, prepend=log_close[0])

    # 2) K线实体：涨跌力度
    body = _安全除法(close - open_, open_)

    # 3) 振幅：震荡强度
    hl_range = _安全除法(high - low, open_)

    # 4) 成交量 / 成交额：用 log1p 再做差分（减少量级差异）
    log_vol = np.log1p(np.maximum(vol, 0.0))
    log_qv = np.log1p(np.maximum(qv, 0.0))
    d_log_vol = np.diff(log_vol, prepend=log_vol[0])
    d_log_qv = np.diff(log_qv, prepend=log_qv[0])

    X = np.column_stack([ret_1h, body, hl_range, d_log_vol, d_log_qv]).astype(np.float64)

    # 轻度截断，避免极端异常值把模型“掰歪”
    X = np.clip(X, -10.0, 10.0)

    特征名 = ["log_ret_1h", "k_body", "hl_range", "d_log_volume", "d_log_quote_volume"]
    时间序列 = df["candle_begin_time"].to_numpy()
    return HMM特征结果(时间序列=时间序列, 特征矩阵=X, 特征名=特征名)

