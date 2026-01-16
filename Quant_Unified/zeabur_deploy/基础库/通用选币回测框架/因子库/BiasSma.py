
def signal(candle_df, param, *args):
    """
    计算因子核心逻辑
    :param candle_df: 单个币种的K线数据
    :param param: 参数，例如在 config 中配置 factor_list 为 ('QuoteVolumeMean', True, 7, 1)
    :param args: 其他可选参数，具体用法见函数实现
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称

    # candle_df['ma'] = candle_df['close'].ewm(span=param, adjust=False).mean()
    candle_df['sma'] = candle_df['close'].rolling(window=param).mean()
    candle_df['bias'] = (candle_df['close'] / candle_df['sma']) - 1
    
    # 对bias因子进行移动平均平滑处理，提高因子的平滑性
    # 使用55期移动平均来平滑bias值，减少噪音和异常跳跃
    # 移除center=True以避免使用未来数据（前视偏差）
    smooth_window = 55
    candle_df['bias_smoothed'] = candle_df['bias'].rolling(window=smooth_window, min_periods=1).mean()
    
    # 对于边界值使用前向填充（仅使用历史数据）
    candle_df['bias_smoothed'] = candle_df['bias_smoothed'].fillna(method='ffill')
    
    # 使用平滑后的bias作为最终因子值
    candle_df[factor_name] = candle_df['bias_smoothed']
    
    # 清理临时列
    candle_df.drop(['bias_smoothed'], axis=1, inplace=True)
    
    return candle_df
