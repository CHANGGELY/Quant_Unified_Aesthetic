"""计算平均主动买入量"""
import pandas as pd


def signal(candle_df, param, *args):
    """
    计算因子核心逻辑
    :param candle_df: 单个币种的K线数据
    :param param: 参数，例如在 config 中配置 factor_list 为 ('Tbr', True, 7, 1)
    :param args: 其他可选参数，具体用法见函数实现
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称

    n = param
    tbr = (candle_df['taker_buy_quote_asset_volume']).rolling(n,min_periods=1).sum() / \
          candle_df['quote_volume'].rolling(n, min_periods=1).sum()

    candle_df[factor_name] = tbr.shift(1)

    return candle_df
