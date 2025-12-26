#!/usr/bin/python3
# -*- coding: utf-8 -*-

import pandas as pd
import numpy  as np


def compute_adaptive_vwap(close, quote_vol, vol, dyn_n):
    """
    close, quote_vol, vol: numpy array
    dyn_n: 自适应窗口长度数组 (int)
    返回 VWAP_adapt 数组
    """
    N = len(close)
    vwap = np.empty(N, dtype=np.float64)
    for i in range(N):
        w = dyn_n[i]
        start = max(0, i - w + 1)
        sum_qv = 0.0
        sum_v = 0.0
        for j in range(start, i + 1):
            sum_qv += quote_vol[j]
            sum_v += vol[j]
        if sum_v == 0:
            vwap[i] = np.nan
        else:
            vwap[i] = sum_qv / sum_v
    return (close - vwap) / vwap



def signal(*args):
    """
    优化版 VWAP 偏离率选币因子
    - 对样本不足的币种自动降权
    """
    df = args[0]
    n = args[1]
    factor_name = args[2]

    k = len(df)

    # 自适应窗口长度
    if k > 0 and k < 1.2*n:
        window = max(int(np.ceil(k * 0.5)), 4)  # 确保最小为1
    else:
        window = n

    # 计算 VWAP
    vwap = df['quote_volume'].rolling(window, min_periods=1).sum() / df['volume'].rolling(window, min_periods=1).sum()
    #波动率调整
    # 使用平滑收盘价，减少偶发 wick 造成的假偏离
    # df['smooth_close'] = df['close'].rolling(5, min_periods=1).mean()

    vol = df['close'].pct_change().rolling(24, min_periods=1).std()
    vol_score = 1 / (1 + 5 * vol)  # 高波动时降权



    #
    df[factor_name] = vol_score*(df['close'] - vwap) / vwap

    return df
