def signal(candle_df, param, *args):
    n = param
    factor_name = args[0]
    close = candle_df['close']
    mid = close.rolling(n, min_periods=1).mean()
    std = close.rolling(n, min_periods=1).std()
    lower = mid - 2 * std.fillna(0)
    candle_df[factor_name] = ((close >= lower) & (close <= mid)).astype(int)
    return candle_df
