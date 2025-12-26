def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    df['tp'] = (df['high'] + df['low'] + df['close']) / 3
    df['ma'] = df['tp'].rolling(window=n, min_periods=1).mean()
    df['md'] = abs(df['tp'] - df['ma']).rolling(window=n, min_periods=1).mean()

    # 计算CCI
    df['cci_raw'] = (df['tp'] - df['ma']) / (df['md'] * 0.015)

    # 用EMA平滑CCI结果
    df[factor_name] = df['cci_raw'].ewm(span=5, adjust=False).mean()

    del df['tp']
    del df['ma']
    del df['md']
    del df['cci_raw']

    return df