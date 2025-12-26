def signal(candle_df, param, *args):

    n = param
    factor_name = args[0]

    oma = candle_df['open'].ewm(span=n, adjust=False).mean()
    hma = candle_df['high'].ewm(span=n, adjust=False).mean()
    lma = candle_df['low'].ewm(span=n, adjust=False).mean()
    cma = candle_df['close'].ewm(span=n, adjust=False).mean()
    tp = (oma + hma + lma + cma) / 4
    ma = tp.ewm(span=n, adjust=False).mean()
    md = (cma - ma).abs().ewm(span=n, adjust=False).mean()
    candle_df[factor_name] = (tp - ma) / md

    return candle_df