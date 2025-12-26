"""
2022  B圈新版课程 | 邢不行
author: 邢不行
微信: xbx6660
"""


def signal(candle_df, param, *args):
    # Volume
    df = candle_df
    n = param
    factor_name = args[0]

    df[factor_name] = df['quote_volume'].rolling(n, min_periods=1).sum()

    return df
