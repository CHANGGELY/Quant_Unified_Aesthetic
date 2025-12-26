"""
AO 因子（Awesome Oscillator，动量震荡）— 量纲归一版本

定义
- 使用中位价 `mid=(high+low)/2` 的短/长均线差作为动量源
- 先对均线差做比例归一：`(SMA_s - SMA_l) / SMA_l`
- 再对结果以 `ATR(l)` 做风险归一，得到跨币种可比的无量纲指标

用途
- 作为前置过滤（方向确认）：AO > 0 表示短期动量强于长期动量
- 也可作为选币因子，但推荐保留主因子（如 VWapBias）主导排名
"""

import numpy as np
import pandas as pd


def _parse_param(param):
    """解析参数，支持 (s,l)、"s,l" 两种写法；默认 (5,34)"""
    if isinstance(param, (tuple, list)) and len(param) >= 2:
        return int(param[0]), int(param[1])
    if isinstance(param, str) and "," in param:
        a, b = param.split(",")
        return int(a), int(b)
    return 5, 34


def _atr(df, n):
    """计算 ATR(n)：真实波动范围的均值，用于风险归一"""
    prev_close = df["close"].shift(1).fillna(df["open"])  # 前收盘价（首根用开盘补齐）
    # 真实波动 TR = max(高-低, |高-前收|, |低-前收|)
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(np.abs(df["high"] - prev_close), np.abs(df["low"] - prev_close)),
    )
    return pd.Series(tr).rolling(n, min_periods=1).mean()  # 滚动均值作为 ATR


def signal(*args):
    """计算单参数 AO 因子并写入列名 `factor_name`"""
    df = args[0]  # K线数据
    param = args[1]  # 参数（支持 "s,l"）
    factor_name = args[2]  # 因子列名
    s, l = _parse_param(param)  # 解析短/长窗口
    eps = 1e-12  # 防除零微量
    mid = (df["high"] + df["low"]) / 2.0  # 中位价
    sma_s = mid.rolling(s, min_periods=1).mean()  # 短均线
    sma_l = mid.rolling(l, min_periods=1).mean()  # 长均线
    atr_l = _atr(df, l)  # 长窗 ATR
    # 比例/ATR 归一：跨币种可比、抗量纲
    ao = ((sma_s - sma_l) / (sma_l + eps)) / (atr_l + eps)
    df[factor_name] = ao.replace([np.inf, -np.inf], 0).fillna(0)  # 安全处理
    return df
