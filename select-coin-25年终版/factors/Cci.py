def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    df['tp'] = (df['high'] + df['low'] + df['close']) / 3
    df['ma'] = df['tp'].rolling(window=n, min_periods=1).mean()
    df['md'] = abs(df['tp'] - df['ma']).rolling(window=n, min_periods=1).mean()
    df[factor_name] = (df['tp'] - df['ma']) / df['md'] / 0.015

    del df['tp']
    del df['ma']
    del df['md']

    return df