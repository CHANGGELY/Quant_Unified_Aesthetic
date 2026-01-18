"""
突破百分比因子 - 计算价格突破n周期高点/低点的百分比幅度
Author: 邢不行框架适配
"""

def signal(candle_df, param, *args):
    """
    计算突破百分比因子
    :param candle_df: 单个币种的K线数据
    :param param: 滚动周期数
    :param args: 其他可选参数
    :return: 包含因子数据的K线数据
    """
    n = param
    factor_name = args[0]
    
    # 计算n周期内的最高价和最低价（排除当期）
    rolling_high = candle_df['high'].shift(1).rolling(n, min_periods=1).max()
    rolling_low = candle_df['low'].shift(1).rolling(n, min_periods=1).min()
    
    # 计算突破高点的百分比
    breakout_high_pct = ((candle_df['close'] - rolling_high) / rolling_high).clip(lower=0)
    
    # 计算跌破低点的百分比（负值）
    breakout_low_pct = ((candle_df['close'] - rolling_low) / rolling_low).clip(upper=0)
    
    # 结合两个方向的突破：正值表示向上突破，负值表示向下突破
    candle_df[factor_name] = breakout_high_pct + breakout_low_pct
    
    return candle_df


def signal_multi_params(df, param_list) -> dict:
    """
    多参数计算版本
    """
    ret = dict()
    for param in param_list:
        n = int(param)
        rolling_high = df['high'].shift(1).rolling(n, min_periods=1).max()
        rolling_low = df['low'].shift(1).rolling(n, min_periods=1).min()
        breakout_high_pct = ((df['close'] - rolling_high) / rolling_high).clip(lower=0)
        breakout_low_pct = ((df['close'] - rolling_low) / rolling_low).clip(upper=0)
        ret[str(param)] = breakout_high_pct + breakout_low_pct
    return ret