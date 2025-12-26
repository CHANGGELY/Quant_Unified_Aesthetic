"""
主动卖出成交额与成交总额的比值
"""


def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    # 优先使用quote维度；若缺失则回退到base维度
    if 'taker_buy_quote_asset_volume' in df.columns and 'quote_volume' in df.columns:
        sell_quote_sum = df['quote_volume'].rolling(n, min_periods=1).sum() - \
                         df['taker_buy_quote_asset_volume'].rolling(n, min_periods=1).sum()
        quote_sum = df['quote_volume'].rolling(n, min_periods=1).sum().replace(0, 1e-10)
        df['Tsr'] = sell_quote_sum / quote_sum
    elif 'taker_buy_base_asset_volume' in df.columns and 'volume' in df.columns:
        sell_base_sum = df['volume'].rolling(n, min_periods=1).sum() - \
                        df['taker_buy_base_asset_volume'].rolling(n, min_periods=1).sum()
        base_sum = df['volume'].rolling(n, min_periods=1).sum().replace(0, 1e-10)
        df['Tsr'] = sell_base_sum / base_sum
    else:
        df['Tsr'] = 0

    # 与 TakerBuyRate 保持一致：窗口内取最大值，增强极端卖压识别
    df[factor_name] = df['Tsr'].rolling(n, min_periods=1).max()

    return df