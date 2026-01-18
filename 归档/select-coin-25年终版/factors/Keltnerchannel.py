def signal(df, param, *args):
    """
    多时间框架确认的Keltner Channel因子
    :param df: K线数据DataFrame
    :param param: ATR周期参数
    :param args: 其他参数
    :return: 包含Keltner Channel因子的DataFrame
    """
    factor_name = args[0] if args else 'keltnerchannel'
    period = int(param)
    atr_time = 1.5
  
    # 短期Keltner Channel
    short_period = max(10, period // 2)
    df['ema_short'] = df['close'].ewm(span=short_period, adjust=False).mean()
  
    # 计算短期ATR
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift(1))
    low_close = abs(df['low'] - df['close'].shift(1))
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr_short'] = tr.ewm(span=short_period, adjust=False).mean()
  
    # 短期通道
    upper_band_short = df['ema_short'] + atr_time * df['atr_short']
    lower_band_short = df['ema_short'] - atr_time * df['atr_short']
  
    # 长期趋势确认
    long_period = period
    df['ema_long'] = df['close'].ewm(span=long_period, adjust=False).mean()
    df['atr_long'] = tr.ewm(span=long_period, adjust=False).mean()
  
    # 长期通道
    upper_band_long = df['ema_long'] + atr_time * df['atr_long']
    lower_band_long = df['ema_long'] - atr_time * df['atr_long']
  
    # 多时间框架信号
    # 短期信号：基于短期通道的位置
    short_position = (df['close'] - df['ema_short']) / (upper_band_short - lower_band_short)
  
    # 长期趋势确认：基于长期通道的位置
    long_position = (df['close'] - df['ema_long']) / (upper_band_long - lower_band_long)
  
    # 综合因子：短期信号 × 长期趋势确认（都标准化到-1到1之间）
    # 使用tanh函数限制极值影响
    combined_signal = np.tanh(short_position * long_position)
  
    df[factor_name] = combined_signal
  
    # 清理临时列
    df.drop(['ema_short', 'ema_long', 'atr_short', 'atr_long'], axis=1, inplace=True)
  