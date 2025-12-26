# -*- coding: utf-8 -*-
"""
CirculatingMcap（近似市值/规模代理因子，时间序列）
说明：
- 真实流通市值需要 circulating_supply，但当前字段缺失，因此这里只能做 proxy。
- proxy 方案：close * rolling_mean(quote_volume)
  直观含义：价格 × 近期“成交额规模”（流动性规模），用于偏好“大/更可交易”的标的。

无未来函数：仅使用 rolling 历史窗口（含当前K线）。
"""

import numpy as np


def signal(*args):
    df = args[0]
    n = int(args[1])
    factor_name = args[2]

    # 1) 近期成交额均值（流动性规模）
    qv_mean = df['quote_volume'].rolling(window=n, min_periods=1).mean()

    # 2) 近似“市值/规模”proxy：价格加权流动性
    mcap_proxy = df['close'] * qv_mean

    # 3) 可选：对数压缩，减少极端值影响（更稳、更适合做排序）
    df[factor_name] = np.log1p(mcap_proxy)

    return df


