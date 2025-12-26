"""VolumeSupportResistance净支撑量指标，用于衡量成交量在支撑和阻力区域的分布情况"""
import pandas as pd
import numpy as np


def signal(candle_df, param, *args):
    """
    计算VolumeSupportResistance（净支撑量）因子核心逻辑
    该因子通过分析价格和成交量的关系，识别支撑和阻力强度，值越大说明支撑越强，价格上涨潜力越大
    
    :param candle_df: 单个币种的K线数据
    :param param: 计算周期参数，通常为14-20
    :param args: 其他可选参数，args[0]为因子名称
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称
    n = param  # 计算周期
    
    # 步骤1: 计算周期内收盘价的均值
    close_mean = candle_df['close'].rolling(window=n, min_periods=1).mean()
    
    # 步骤2: 计算支撑成交量（收盘价低于均值时的成交量和）
    # 创建一个布尔序列，标记收盘价低于均值的情况
    support_condition = candle_df['close'] < close_mean
    # 将符合条件的成交量保留，否则设为0，然后计算滚动和
    support_volume = candle_df['volume'].where(support_condition, 0).rolling(window=n, min_periods=1).sum()
    
    # 步骤3: 计算阻力成交量（收盘价高于均值时的成交量和）
    # 创建一个布尔序列，标记收盘价高于均值的情况
    resistance_condition = candle_df['close'] > close_mean
    # 将符合条件的成交量保留，否则设为0，然后计算滚动和
    resistance_volume = candle_df['volume'].where(resistance_condition, 0).rolling(window=n, min_periods=1).sum()
    
    # 步骤4: 计算支撑成交量和阻力成交量的比值
    # 为避免除零错误，当阻力成交量为0时，设为一个很小的值
    resistance_volume_safe = resistance_volume.replace(0, 1e-9)
    # 计算支撑/阻力比值作为因子值
    # 为了标准化和稳定性，可以对结果进行对数处理或限制范围
    support_resistance_ratio = support_volume / resistance_volume_safe
    
    # 存储因子值到candle_df中
    candle_df[factor_name] = support_resistance_ratio
    
    # 可选：存储中间计算结果，便于调试和分析
    candle_df[f'{factor_name}_close_mean'] = close_mean
    candle_df[f'{factor_name}_support_volume'] = support_volume
    candle_df[f'{factor_name}_resistance_volume'] = resistance_volume
    
    return candle_df