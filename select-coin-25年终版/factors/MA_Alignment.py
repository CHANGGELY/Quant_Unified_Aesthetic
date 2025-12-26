"""
邢不行™️选币框架
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662

移动平均线排列 (MA_Alignment) 因子
"""

import pandas as pd
import numpy as np

def calculate_ma_alignment(close, short_window=5, medium_window=20, long_window=60):
    """
    计算移动平均线排列因子
    :param close: 收盘价序列
    :param short_window: 短期移动平均线周期
    :param medium_window: 中期移动平均线周期
    :param long_window: 长期移动平均线周期
    :return: 移动平均线排列因子序列（1表示多头排列，-1表示空头排列，0表示非排列状态）
    """
    # 计算不同周期的移动平均线
    ma_short = close.rolling(window=short_window).mean()
    ma_medium = close.rolling(window=medium_window).mean()
    ma_long = close.rolling(window=long_window).mean()

    # 判断是否多头排列（短期MA > 中期MA > 长期MA）
    bull_alignment = (ma_short > ma_medium) & (ma_medium > ma_long)

    # 判断是否空头排列（短期MA < 中期MA < 长期MA）
    bear_alignment = (ma_short < ma_medium) & (ma_medium < ma_long)

    # 判断是否死叉（短期MA < 中期MA < 长期MA）
    dead_alignment = (ma_short < ma_medium) & (ma_short < ma_long)

    # 创建排列因子序列，默认为0（非排列状态）
    alignment = np.zeros(len(close))

    # 设置多头排列为1
    alignment[bull_alignment] = 1

    # 设置空头排列为-1
    alignment[bear_alignment] = -1

    return alignment

def signal(candle_df, param, *args):
    """
    计算移动平均线排列因子
    :param candle_df: 单个币种的K线数据
    :param param: 移动平均线周期参数（可以是一个数字或元组）
    :param args: 其他可选参数，args[0]为因子名称
    :return: 包含因子数据的K线数据
    """
    factor_name = args[0]  # 因子名称

    # 解析参数
    if isinstance(param, (list, tuple)) and len(param) >= 3:
        # 如果参数是列表或元组，且长度至少为3
        short_period = param[0]
        medium_period = param[1]
        long_period = param[2]
    else:
        # 如果参数是单个数字，使用默认的比例关系
        short_period = param
        medium_period = param * 2  # 中期是短期的2倍
        long_period = param * 5    # 长期是短期的5倍

    # 检查数据长度是否足够计算最长的移动平均线
    if len(candle_df) < long_period:
        # 如果数据长度不足，返回NaN值
        candle_df[factor_name] = np.nan
        return candle_df

    try:
        # 计算移动平均线排列
        alignment_values = calculate_ma_alignment(
            candle_df['close'],
            short_window=short_period,
            medium_window=medium_period,
            long_window=long_period
        )

        candle_df[factor_name] = alignment_values
    except Exception as e:
        # 如果计算过程中出现错误，返回NaN值
        print(f"计算移动平均线排列因子时出错: {e}")
        candle_df[factor_name] = np.nan

    return candle_df