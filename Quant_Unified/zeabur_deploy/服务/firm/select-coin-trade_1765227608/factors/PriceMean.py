"""
Quant Unified 量化交易系统
PriceMean.py
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
    n = param  # 滚动周期数，用于涨跌幅计算
    factor_name = args[0]  # 从额外参数中获取因子名称

    quote_volume = candle_df['quote_volume'].rolling(n, min_periods=1).mean()
    volume = candle_df['volume'].rolling(n, min_periods=1).mean()

    candle_df[factor_name] = quote_volume / volume  # 成交额/成交量，计算出成交均价

    return candle_df
