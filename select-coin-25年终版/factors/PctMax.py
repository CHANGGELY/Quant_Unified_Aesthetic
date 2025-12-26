import pandas as pd


def signal(candle_df, param, *args):
    """
    PctMax 因子：
    计算当前收盘价相对于过去 param 根 K 线内最高收盘价的百分比位置：
        PctMax = close / rolling_max(close, param) - 1
    """
    n = param  # 滚动窗口长度
    factor_name = args[0]  # 因子名称，例如 'PctMax_30'

    # 过去 n 根 K 线的最高收盘价
    rolling_max_close = candle_df['close'].rolling(n, min_periods=1).max()

    # 当前价格相对最高价的回撤比例（0 表示在最高点，负值表示回撤）
    candle_df[factor_name] = candle_df['close'] / rolling_max_close - 1

    return candle_df
