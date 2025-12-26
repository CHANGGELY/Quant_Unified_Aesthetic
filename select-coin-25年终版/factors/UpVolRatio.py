import numpy as np
import pandas as pd

def signal(candle_df, param, *args):
    n = int(param)
    factor_name = args[0]

    # 以收盘价相对前一根的变化划分上涨/下跌
    diff = candle_df['close'].diff()
    diff.fillna(candle_df['close'] - candle_df['open'], inplace=True)

    up_volume = np.where(diff >= 0, candle_df['volume'], 0.0)
    down_volume = np.where(diff < 0, candle_df['volume'], 0.0)

    up_sum = (pd.Series(up_volume, index=candle_df.index)
              .rolling(n, min_periods=1).sum())
    down_sum = (pd.Series(down_volume, index=candle_df.index)
                .rolling(n, min_periods=1).sum())

    denom = (up_sum + down_sum).replace(0, 1e-12)
    candle_df[factor_name] = (up_sum / denom).clip(0, 1)

    return candle_df