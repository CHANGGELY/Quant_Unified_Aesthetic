import pandas as pd


def signal(candle_df, param, *args):
    """
    Zfstd：涨跌幅标准差（波动率）
    - 计算 close 的 1期涨跌幅 pct_change(1)
    - 在 param 窗口上计算标准差 std
    - 无未来函数：仅使用当前及历史数据 rolling
    """
    factor_name = args[0]

    ret = candle_df['close'].pct_change(1)
    candle_df[factor_name] = ret.rolling(param, min_periods=1).std(ddof=0)  # ddof=0 更稳定

    return candle_df
