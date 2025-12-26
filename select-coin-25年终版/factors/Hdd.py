def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]
    factor = df['close'] / df['high'].rolling(n, min_periods=1).max()
    df[factor_name] = factor

    return df