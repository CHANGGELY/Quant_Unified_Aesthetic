"""
波动率调整时间序列动量(VATSM)因子
基于市场波动性动态调整回溯期的动量策略

版权所有 ©️ 2024
作者: [你的名字]
微信: [你的微信号]

参考: 数据科学实战知识星球 - VATSM策略解析
"""

import numpy as np
import pandas as pd
from collections import deque
import math

def signal(candle_df, param, *args):
    """
    计算VATSM因子核心逻辑
    
    参数:
    :param candle_df: 单个币种的K线数据
    :param param: 参数，包含最小和最大回溯期 (lb_min, lb_max)
    :param args: 其他可选参数，args[0]为因子名称
    
    返回:
    :return: 包含VATSM因子数据的K线数据
    """
    # 解析参数
    if isinstance(param, (list, tuple)) and len(param) >= 2:
        lb_min, lb_max = param[0], param[1]
    else:
        lb_min, lb_max = 10, 60  # 默认值
    
    factor_name = args[0]  # 从额外参数中获取因子名称
    
    # 初始化缓冲区
    vol_short_win = 20  # 短期波动率计算窗口
    vol_long_win = 60   # 长期波动率计算窗口
    ratio_cap = 0.9     # 波动率比率上限
    eps = 1e-12         # 避免除零的小量
    
    short_buf = deque(maxlen=vol_short_win)
    long_buf = deque(maxlen=vol_long_win)
    
    # 准备结果列
    candle_df[factor_name] = np.nan
    
    # 计算对数收益率
    close_prices = candle_df['close'].values
    log_returns = np.log(close_prices[1:] / close_prices[:-1])
    
    for i in range(1, len(candle_df)):
        if i > 1:
            ret = log_returns[i-1]
            short_buf.append(ret)
            long_buf.append(ret)
        
        # 计算波动率
        vol_s = np.std(list(short_buf), ddof=1) if len(short_buf) > 1 else 0.0
        vol_l = np.std(list(long_buf), ddof=1) if len(long_buf) > 1 else 0.0
        
        # 计算波动率比率
        ratio = min(ratio_cap, max(0.0, vol_s / max(vol_l, eps)))
        
        # 动态回溯期
        lb = int(lb_min + (lb_max - lb_min) * (1.0 - ratio))
        lb = max(lb_min, min(lb, lb_max))
        
        # 计算动量
        if i > lb:
            past = close_prices[i - lb]
            mom = 0.0 if past <= 0 else (close_prices[i] - past) / past
            candle_df.loc[candle_df.index[i], factor_name] = mom
    
    return candle_df


def signal_volatility(candle_df, param, *args):
    """
    计算波动率因子，用于辅助VATSM策略
    
    参数:
    :param candle_df: 单个币种的K线数据
    :param param: 参数，波动率计算窗口
    :param args: 其他可选参数，args[0]为因子名称
    
    返回:
    :return: 包含波动率因子数据的K线数据
    """
    factor_name = args[0]
    
    # 计算对数收益率
    close_prices = candle_df['close'].values
    log_returns = np.log(close_prices[1:] / close_prices[:-1])
    
    # 初始化结果列
    candle_df[factor_name] = np.nan
    
    # 计算滚动波动率
    for i in range(param, len(log_returns)):
        window_returns = log_returns[i-param:i]
        vol = np.std(window_returns, ddof=1)
        candle_df.loc[candle_df.index[i+1], factor_name] = vol
    
    return candle_df