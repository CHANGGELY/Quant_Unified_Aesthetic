"""
邢不行™️选币框架
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662

布林带宽变化率因子 - 计算带宽与均值的比值
"""

import pandas as pd
import numpy as np

def calculate_bb_width_ratio(close, window=12, lookback_period=12, num_std=2):
    """
    计算布林带宽与历史均值的比值
    :param close: 收盘价序列
    :param window: 布林带计算周期
    :param lookback_period: 历史均值计算周期
    :param num_std: 标准差倍数
    :return: 带宽比值序列
    """
    # 计算中轨（移动平均）
    middle_band = close.rolling(window=window).mean()

    # 计算标准差
    std = close.rolling(window=window).std()

    # 计算上轨和下轨
    upper_band = middle_band + (std * num_std)
    lower_band = middle_band - (std * num_std)

    # 计算布林带宽度 (上轨-下轨)/中轨
    bb_width = (upper_band - lower_band) / middle_band

    # 计算带宽的历史均值
    bb_width_ma = bb_width.rolling(window=lookback_period).mean()

    # 计算带宽与历史均值的比值
    bb_width_ratio = bb_width / bb_width_ma-1

    return bb_width_ratio

def signal(candle_df, param, *args):
    """
    计算布林带宽变化率因子
    :param candle_df: 单个币种的K线数据
    :param param: 布林带计算周期
    :param args: 其他可选参数，args[0]为因子名称
    :return: 包含因子数据的K线数据
    """
    n = param  # 布林带计算周期
    factor_name = args[0]  # 因子名称

    # 检查数据长度是否足够计算
    if len(candle_df) < n * 2:  # 需要足够的数据计算带宽和其均值
        # 如果数据长度不足，返回NaN值
        candle_df[factor_name] = np.nan
        return candle_df

    try:
        # 计算布林带宽比值
        bb_width_ratio_values = calculate_bb_width_ratio(
            candle_df['close'],
            window=n,
            lookback_period=n,  # 使用相同的周期计算历史均值
            num_std=2
        )

        candle_df[factor_name] = bb_width_ratio_values
    except Exception as e:
        # 如果计算过程中出现错误，返回NaN值
        print(f"计算布林带宽变化率时出错: {e}")
        candle_df[factor_name] = np.nan

    return candle_df