import pandas as pd
import numpy as np


def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    df['diff'] = df['close'].diff()
    df['diff'].fillna(df['close'] - df['open'], inplace=True)
    df['up'] = np.where(df['diff'] >= 0, 1, 0) * df['volume']
    df['down'] = np.where(df['diff'] < 0, -1, 0) * df['volume']
    a = df['up'].rolling(n, min_periods=1).sum()
    b = df['down'].abs().rolling(n, min_periods=1).sum()
    df[factor_name] =  a - b

    del df['diff'], df['up'], df['down']

    return df