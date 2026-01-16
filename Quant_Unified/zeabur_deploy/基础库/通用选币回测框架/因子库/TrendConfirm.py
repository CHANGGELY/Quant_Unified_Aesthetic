# TrendConfirm.py
def signal(candle_df, param, *args):
    """
    短周期均线趋势确认因子
    param: n，短期均线长度，比如 50、100
    """
    df = candle_df
    factor_name = args[0]

    df['ma_short'] = df['close'].rolling(param, min_periods=1).mean()
    df[factor_name] = (df['close'] > df['ma_short']).astype(int)

    return df
