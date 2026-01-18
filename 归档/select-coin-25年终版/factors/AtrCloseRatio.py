

import numpy as np
import pandas as pd

def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    # 1. 计算ATR（平均真实波幅）的核心组件：真实波幅TR
    # TR = max(当前最高价-当前最低价, |当前最高价-前一期收盘价|, |当前最低价-前一期收盘价|)
    df['tr1'] = df['high'] - df['low']  # 当日高低价差
    df['tr2'] = abs(df['high'] - df['close'].shift(1))  # 当日最高价与前一日收盘价差的绝对值
    df['tr3'] = abs(df['low'] - df['close'].shift(1))  # 当日最低价与前一日收盘价差的绝对值
    df['TR'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)  # 真实波幅（取三个值的最大值）

    # 2. 计算n周期ATR（滚动平均真实波幅）
    df['ATR'] = df['TR'].rolling(n, min_periods=1).mean()  # 简单移动平均（可改为ewm平滑，按需调整）

    # 3. 计算ATR与收盘价比值（避免收盘价为0的极端情况，用replace替换为NA）
    df['AtrCloseRatio'] = df['ATR'] / df['close'].replace(0, np.nan)
    df[factor_name] = df['AtrCloseRatio']

    # （可选）删除临时列（若不需要保留TR、ATR中间结果）
    df.drop(['tr1', 'tr2', 'tr3'], axis=1, inplace=True)


    return df