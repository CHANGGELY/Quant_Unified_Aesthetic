import pandas as pd


def signal(candle_df, param, *args):
    factor_name = args[0]
    candle_df[factor_name] = candle_df['close'].pct_change(1).abs().rolling(param, min_periods=1).mean()
    return candle_df
