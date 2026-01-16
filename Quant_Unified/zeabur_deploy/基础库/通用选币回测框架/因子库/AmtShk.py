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
    short = param[0]
    long = param[1]

    short_std = candle_df['quote_volume'].rolling(short).std()
    long_std = candle_df['quote_volume'].rolling(long).std()
    candle_df[factor_name] = short_std / long_std


    # # 更加高效的一种写法
    # pct = candle_df['close'].pct_change()
    # up = pct.where(pct > 0, 0)
    # down = pct.where(pct < 0, 0).abs()
    #
    # A = up.rolling(param, min_periods=1).sum()
    # B = down.rolling(param, min_periods=1).sum()
    #
    # candle_df[factor_name] = A / (A + B)

    return candle_df
