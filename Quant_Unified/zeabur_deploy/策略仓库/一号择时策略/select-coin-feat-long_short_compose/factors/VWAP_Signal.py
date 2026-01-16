# -*- coding: utf-8 -*-
"""
VWAP Signal Factor
Signal: 1 if Close > VWAP, -1 if Close < VWAP
"""
import pandas as pd

def signal(*args):
    """
    计算 VWAP 信号
    args[0]: df
    args[1]: n (rolling window)
    args[2]: factor_name
    """
    df = args[0]
    n = args[1]
    factor_name = args[2]

    # Calculate VWAP
    # VWAP = Sum(Price * Volume) / Sum(Volume)
    # Using quote_volume (Price * Volume) directly if available
    vwap = (df['quote_volume'].rolling(n, min_periods=1).sum() /
            df['volume'].rolling(n, min_periods=1).sum())

    # Signal Logic
    # Close > VWAP -> Long (1)
    # Close < VWAP -> Short (-1)
    # Note: This is a raw signal. In actual backtest, shift(1) is usually applied to avoid lookahead bias.
    
    # Initialize with NaN
    df[factor_name] = 0
    
    mask_long = df['close'] > vwap
    mask_short = df['close'] < vwap
    
    df.loc[mask_long, factor_name] = 1
    df.loc[mask_short, factor_name] = -1

    return df
