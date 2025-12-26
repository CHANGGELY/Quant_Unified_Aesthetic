import pandas as pd


def signal(candle_df: pd.DataFrame, param, *args):
    n = param  # 滚动周期数，用于涨跌幅计算
    factor_name = args[0]  # 从额外参数中获取因子名称

    max_high = candle_df["high"].rolling(n, min_periods=1).max()
    candle_df[factor_name] = candle_df["close"] / max_high

    return candle_df
