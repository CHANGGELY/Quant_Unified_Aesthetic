def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    # volume1 = df['volume'].rolling(int(n/2), min_periods=1).mean()
    volume1 = df['volume'].rolling(8, min_periods=1).mean()
    volume2 = df['volume'].rolling(n, min_periods=1).mean()
    df[factor_name] = volume1 - volume2

    return df