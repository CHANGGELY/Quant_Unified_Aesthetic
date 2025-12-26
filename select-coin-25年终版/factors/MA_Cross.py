"""币种的短周期均线和长周期均线交叉关系"""

import numpy as np

def signal(candle_df, param, *args):
    """
    计算因子核心逻辑
    :param candle_df: 单个币种的K线数据
    :param param: 参数，包含短周期和长周期的元组，例如(40, 400)
    :param args: 其他可选参数，具体用法见函数实现
    :return: 包含因子数据的 K 线数据
    """
    short_period, long_period = int(param[0]), int(param[1])
    factor_name = args[0]  # 从额外参数中获取因子名称

    ma_short = candle_df['close'].rolling(window=short_period, min_periods=1).mean()
    ma_long = candle_df['close'].rolling(window=long_period, min_periods=1).mean()
    candle_df[factor_name] = np.where(ma_short > ma_long, 1, 0)

    return candle_df

