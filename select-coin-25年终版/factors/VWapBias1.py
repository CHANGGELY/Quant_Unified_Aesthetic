# -*- coding: utf-8 -*-
"""
近似处置效应因子 | 构建自 VWAP 偏离率
author: 邢不行框架适配 
"""

def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    # 计算VWAP_n
    vwap = (df['quote_volume'].rolling(n, min_periods=1).sum() /
            df['volume'].rolling(n, min_periods=1).sum())

    # 因子：收盘价与VWAP的偏离率
    vwap_bias_value = (df['close'] - vwap) / vwap
    
    # 保存到指定的因子名列和固定的'vwap_bias1'列，确保图表绘制能找到
    df[factor_name] = vwap_bias_value
    df['vwap_bias1'] = vwap_bias_value

    return df


def signal_multi_params(df, param_list) -> dict:
    """
    多参数计算版本
    """
    ret = dict()
    for param in param_list:
        n = int(param)
        vwap = (df['quote_volume'].rolling(n, min_periods=1).sum() /
                df['volume'].rolling(n, min_periods=1).sum())
        ret[str(param)] = (df['close'] - vwap) / vwap
    return ret