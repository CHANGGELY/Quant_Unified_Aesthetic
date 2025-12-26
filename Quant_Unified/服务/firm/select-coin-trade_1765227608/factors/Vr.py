"""
Quant Unified 量化交易系统
Vr.py
"""

import numpy as np


def signal(candle_df, param, *args):
    """
    计算因子核心逻辑
    :param candle_df: 单个币种的K线数据
    :param param: 参数，例如在 config 中配置 factor_list 为 ('QuoteVolumeMean', True, 7, 1)
    :param args: 其他可选参数，具体用法见函数实现
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称

    candle_df['av'] = np.where(candle_df['close'] > candle_df['close'].shift(1), candle_df['volume'], 0)
    candle_df['bv'] = np.where(candle_df['close'] < candle_df['close'].shift(1), candle_df['volume'], 0)
    candle_df['cv'] = np.where(candle_df['close'] == candle_df['close'].shift(1), candle_df['volume'], 0)

    avs = candle_df['av'].rolling(param, min_periods=1).sum()
    bvs = candle_df['bv'].rolling(param, min_periods=1).sum()
    cvs = candle_df['cv'].rolling(param, min_periods=1).sum()

    candle_df[factor_name] = (avs + 0.5 * cvs) / (bvs + 0.5 * cvs)

    return candle_df
