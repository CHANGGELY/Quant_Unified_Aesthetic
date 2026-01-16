def signal(candle_df, param, *args):
    """
    计算AO指标核心逻辑
    :param candle_df: 单个币种的K线数据
    :param param: 参数（此处未直接使用，因AO周期固定为5和34）
    :param args: 其他可选参数，第一个元素为因子列名
    :return: 包含AO因子数据的K线数据
    """
    # 从额外参数中获取因子名称
    factor_name = args[0]  
    n, m=param
    # 计算中位价格（最高价与最低价的平均值）
    median_price = (candle_df['high'] + candle_df['low']) / 2.0
    
    # 计算AO指标：5周期SMA减去34周期SMA[1,6,8](@ref)
    short_sma = median_price.rolling(window=n, min_periods=n).mean()
    long_sma = median_price.rolling(window=m, min_periods=m).mean()
    candle_df[factor_name] = (short_sma - long_sma) / long_sma
    
    return candle_df