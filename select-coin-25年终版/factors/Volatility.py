# -*- coding: utf-8 -*-
"""
波动率因子 | 基于价格变化率的标准差
author: 邢不行框架适配 
"""

def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    # 计算价格变化率
    price_change = df['close'].pct_change()
    
    # 计算n期波动率（标准差）
    df[factor_name] = price_change.rolling(n, min_periods=1).std()

    return df


def signal_multi_params(df, param_list) -> dict:
    """
    多参数计算版本
    """
    ret = dict()
    for param in param_list:
        n = int(param)
        price_change = df['close'].pct_change()
        ret[str(param)] = price_change.rolling(n, min_periods=1).std()
    return ret