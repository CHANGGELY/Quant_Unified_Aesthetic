def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    df['Tbr'] = (df['taker_buy_quote_asset_volume'].rolling(n, min_periods = 1).sum() /
                 df['quote_volume'].rolling(n, min_periods=1).sum())

    df[factor_name] = df['Tbr']

    return df
