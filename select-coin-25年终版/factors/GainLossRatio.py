"""
涨幅跌幅比值因子 | 计算n周期涨幅与n周期跌幅绝对值的比值
用于衡量价格上涨动能相对于下跌动能的强度
比值 > 1 表示上涨动能强于下跌动能，比值 < 1 表示下跌动能强于上涨动能
"""

import pandas as pd
import numpy as np


def signal(*args):
    """
    计算涨幅跌幅比值因子
    比值 = n周期涨幅总和 / n周期跌幅绝对值总和
    
    :param args[0]: K线数据DataFrame
    :param args[1]: 计算周期n
    :param args[2]: 因子列名
    :return: 包含因子值的DataFrame
    """
    df = args[0]
    n = args[1]
    factor_name = args[2]
    
    # 计算每个周期的涨跌幅
    df['pct_change'] = df['close'].pct_change()
    
    # 分离涨幅（正数）和跌幅（负数）
    df['gain'] = np.where(df['pct_change'] > 0, df['pct_change'], 0)
    df['loss'] = np.where(df['pct_change'] < 0, df['pct_change'], 0)
    
    # 计算n周期涨幅总和
    gain_sum = df['gain'].rolling(n, min_periods=1).sum()
    
    # 计算n周期跌幅绝对值总和
    loss_abs_sum = df['loss'].abs().rolling(n, min_periods=1).sum()
    
    # 计算比值，避免除零
    ratio = gain_sum / (loss_abs_sum + 1e-9)
    
    # 处理异常值
    df[factor_name] = ratio.replace([np.inf, -np.inf], np.nan)
    
    # 清理临时列
    df.drop(['pct_change', 'gain', 'loss'], axis=1, inplace=True, errors='ignore')
    
    return df


def signal_multi_params(df, param_list) -> dict:
    """
    多参数计算版本，支持批量计算不同周期的涨幅跌幅比值
    可以有效提升回测、实盘 cal_factor 的速度
    
    :param df: K线数据的DataFrame
    :param param_list: 参数列表，如 [24, 48, 72]
    :return: 字典，key为参数值（字符串），value为因子值Series
    """
    ret = dict()
    
    # 计算每个周期的涨跌幅（只需计算一次）
    pct_change = df['close'].pct_change()
    gain = np.where(pct_change > 0, pct_change, 0)
    loss = np.where(pct_change < 0, pct_change, 0)
    
    for param in param_list:
        n = int(param)
        
        # 计算n周期涨幅总和
        gain_sum = pd.Series(gain, index=df.index).rolling(n, min_periods=1).sum()
        
        # 计算n周期跌幅绝对值总和
        loss_abs_sum = pd.Series(loss, index=df.index).abs().rolling(n, min_periods=1).sum()
        
        # 计算比值
        ratio = gain_sum / (loss_abs_sum + 1e-9)
        
        # 处理异常值
        ret[str(param)] = ratio.replace([np.inf, -np.inf], np.nan)
    
    return ret


