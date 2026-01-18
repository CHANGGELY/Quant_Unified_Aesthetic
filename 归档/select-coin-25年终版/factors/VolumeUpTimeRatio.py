import pandas as pd
import numpy as np

def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    # 1. 计算基础涨跌
    df['diff'] = df['close'].diff()
    df['diff'].fillna(df['close'] - df['open'], inplace=True)
    
    # 2. 提取上涨时的成交量
    # 如果涨(diff>=0)，取volume；否则取0
    df['vol_up'] = np.where(df['diff'] >= 0, df['volume'], 0)
    
    # 3. 滚动统计
    # A: N周期内上涨K线的成交量总和
    df['sum_vol_up'] = df['vol_up'].rolling(n, min_periods=1).sum()
    # B: N周期内的总成交量
    df['sum_vol_total'] = df['volume'].rolling(n, min_periods=1).sum()
    
    # 4. 计算比例
    # 处理除数为0的情况（虽然极少见），用 replace 避免报错
    df[factor_name] = df['sum_vol_up'] / df['sum_vol_total'].replace(0, np.nan)

    return df