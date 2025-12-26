def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    # n小时最高收盘价
    df['n_hour_close'] = df['close'].rolling(n).max()

    # 当前价格距离最高价的回撤比例（0~1）
    df['ratio'] = df['n_hour_close'] / df['close'] - 1

    # 取过去n小时内的最大回撤强度
    df[factor_name] = df['ratio'].rolling(n).max()

    return df
