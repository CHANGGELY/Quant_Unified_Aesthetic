# -*- coding: utf-8 -*-
"""
近似处置效应因子 | 构建自 VWAP 偏离率
author: 邢不行框架适配 
"""

def signal(*args):
    df = args[0]
    n1 = args[1][0] 
    n2 = args[1][1] 
    factor_name = args[2]

    # 计算VWAP_n
    vwap = (df['quote_volume'].rolling(n1, min_periods=1).sum() /
            df['volume'].rolling(n1, min_periods=1).sum())

    # 原始因子
    raw_factor = (df['close'] - vwap) / vwap
    
    # 因子的变化率（环比）
    df[factor_name] = raw_factor.pct_change(n2)
    
    return df