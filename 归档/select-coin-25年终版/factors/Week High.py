import pandas as pd
import numpy as np

def signal(candle_df, param, *args):
    """
   新高择时因子（二值开/关）

    param: n，滚动窗口长度（如 252 日 / 24*180 小时等）
    args:
        args[0]: factor_name
        args[1]: threshold（可选），比如 0.9，表示 close / rolling_high >= 0.9 才认为是“强势期”

    输出:
    df[factor_name] ∈ {0,1}
        1: 市场强势（接近 n 期新高），可以开仓/加仓
        0: 市场较弱，建议减仓或空仓
    """
    df = candle_df.copy()
    factor_name = args[0]

    n = param
    threshold = args[1] if len(args) > 1 else 0.9

    df['rolling_high'] = df['close'].rolling(n, min_periods=1).max()
    df['rolling_high_safe'] = df['rolling_high'].replace(0, np.nan)

    score = df['close'] / df['rolling_high_safe']
    score = score.clip(upper=1.0)

    # 二值开关：接近过去高点才=1
    df[factor_name] = (score >= threshold).astype(int)

    df[factor_name] = df[factor_name].fillna(0)
    df.drop(['rolling_high', 'rolling_high_safe'], axis=1, inplace=True)

    return df
