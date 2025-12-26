import pandas as pd


def signal(candle_df, param, *args):
    """
    PctChangeMax 因子：
    计算过去 param 根 K 线中，单根 K 线的最大正向涨幅：
        先计算 ret_1 = close / close.shift(1) - 1
        再在窗口内 rolling(param).max()
    """
    n = param  # 滚动窗口长度
    factor_name = args[0]  # 因子名称，例如 'PctChangeMax_20'

    # 逐根 K 线的 1 步涨跌幅
    ret_1 = candle_df['close'].pct_change(1)

    # 滚动窗口内的最大“正向涨幅”
    candle_df[factor_name] = ret_1.rolling(n, min_periods=1).max()

    return candle_df
