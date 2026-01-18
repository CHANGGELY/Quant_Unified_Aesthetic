"""换手率因子，用于计算币种的换手率"""
import numpy as np


def signal(candle_df, param, *args):
    """
    计算因子核心逻辑
    :param candle_df: 单个币种的K线数据
    :param param: 参数
    :param args: 其他可选参数，具体用法见函数实现
    :return: 包含因子数据的 K 线数据
    """
    n = param  # 滚动周期数，用于换手率计算
    factor_name = args[0]  # 从额外参数中获取因子名称

    volume_mean = candle_df['quote_volume'].rolling(n, min_periods=1).mean()
    price_mean = candle_df['close'].rolling(n, min_periods=1).mean()
    price_mean = price_mean.replace(0, np.nan)

    turnover_rate = volume_mean/price_mean
    candle_df[factor_name] = turnover_rate

    return candle_df
