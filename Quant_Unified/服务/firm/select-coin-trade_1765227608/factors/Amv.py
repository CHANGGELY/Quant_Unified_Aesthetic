"""
Quant Unified 量化交易系统
Amv.py
"""

"""涨跌幅因子，用于计算币种的涨跌幅"""


def signal(candle_df, param, *args):
    """
    计算因子核心逻辑
    :param candle_df: 单个币种的K线数据
    :param param: 参数，例如在 config 中配置 factor_list 为 ('QuoteVolumeMean', True, 7, 1)
    :param args: 其他可选参数，具体用法见函数实现
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称

    AMOV = candle_df['volume'] * (candle_df['open'] + candle_df['close']) / 2
    AMV1 = AMOV.rolling(param).sum() / candle_df['volume'].rolling(param).sum()

    AMV1_min = AMV1.rolling(param).min()
    AMV1_max = AMV1.rolling(param).max()

    candle_df[factor_name] = (AMV1 - AMV1_min) / (AMV1_max - AMV1_min)

    return candle_df
