"""
Quant Unified 量化交易系统
Rsi.py
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

    candle_df['pct'] = candle_df['close'].pct_change()  # 计算涨跌幅
    candle_df['up'] = candle_df['pct'].where(candle_df['pct'] > 0, 0)
    candle_df['down'] = candle_df['pct'].where(candle_df['pct'] < 0, 0).abs()

    candle_df['A'] = candle_df['up'].rolling(param, min_periods=1).sum()
    candle_df['B'] = candle_df['down'].rolling(param, min_periods=1).sum()

    candle_df[factor_name] = candle_df['A'] / (candle_df['A'] + candle_df['B'])

    del candle_df['pct'], candle_df['up'], candle_df['down'], candle_df['A'], candle_df['B']

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
