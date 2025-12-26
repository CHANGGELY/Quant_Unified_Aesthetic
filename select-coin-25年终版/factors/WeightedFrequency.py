"""加权频率因子，基于价格波动频率和成交量加权计算

加权频率因子通过以下步骤计算：
1. 计算价格涨跌方向的变化频率（即反转次数）
2. 使用成交量作为权重，对频率进行加权处理
3. 对结果进行标准化处理，使其范围在[-1, 1]之间

该因子可以捕捉市场情绪的变化频率，高频率通常表示市场波动剧烈，
低频率通常表示市场处于趋势中，适合作为选币策略的参考因子。
"""
import pandas as pd
import numpy as np


def signal(candle_df, param, *args):
    """
    计算加权频率因子核心逻辑
    
    :param candle_df: 单个币种的K线数据
    :param param: 计算周期参数，可以是单个整数(如20)或包含多个参数的元组(如(20, 1))
    :param args: 其他可选参数，args[0]为因子名称
    :return: 包含加权频率因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称
    
    # 解析参数，支持单个参数或多个参数的元组
    if isinstance(param, (list, tuple)) and len(param) >= 1:
        n = param[0]  # 计算周期
        # 如果有第二个参数，可以用于调整权重敏感性
        weight_sensitivity = param[1] if len(param) > 1 else 1
    else:
        # 兼容单参数模式
        n = param
        weight_sensitivity = 1
    
    # 步骤1: 计算价格涨跌方向
    # 收盘价变化率
    candle_df['price_change'] = candle_df['close'].pct_change()
    # 涨跌方向：1表示上涨，-1表示下跌，0表示不变
    candle_df['direction'] = np.where(candle_df['price_change'] > 0, 1, 
                                     np.where(candle_df['price_change'] < 0, -1, 0))
    
    # 步骤2: 计算方向变化次数（反转次数）
    # 方向变化标记：1表示方向改变，0表示方向不变
    candle_df['direction_change'] = (candle_df['direction'] != candle_df['direction'].shift(1)).astype(int)
    
    # 步骤3: 计算n周期内的方向变化频率
    # 频率 = n周期内方向变化次数 / n
    candle_df['direction_frequency'] = candle_df['direction_change'].rolling(window=n, min_periods=1).sum() / n
    
    # 步骤4: 计算成交量权重
    # 对成交量进行标准化处理，使其范围在[0,1]之间
    volume_rolling_max = candle_df['volume'].rolling(window=n, min_periods=1).max()
    volume_rolling_min = candle_df['volume'].rolling(window=n, min_periods=1).min()
    
    # 避免除零错误
    candle_df['volume_weight'] = np.where(
        volume_rolling_max == volume_rolling_min,
        0.5,  # 成交量无变化时设为中性权重
        (candle_df['volume'] - volume_rolling_min) / (volume_rolling_max - volume_rolling_min)
    )
    
    # 调整权重敏感性
    candle_df['volume_weight'] = candle_df['volume_weight'] ** weight_sensitivity
    
    # 步骤5: 计算加权频率因子
    # 加权频率 = 方向变化频率 * 成交量权重
    candle_df[f'{factor_name}_Raw'] = candle_df['direction_frequency'] * candle_df['volume_weight']
    
    # 步骤6: 对因子值进行标准化处理，使其范围在[-1, 1]之间
    # 先计算n周期内的最大值和最小值
    raw_rolling_max = candle_df[f'{factor_name}_Raw'].rolling(window=n, min_periods=1).max()
    raw_rolling_min = candle_df[f'{factor_name}_Raw'].rolling(window=n, min_periods=1).min()
    
    # 避免除零错误
    candle_df[factor_name] = np.where(
        raw_rolling_max == raw_rolling_min,
        0,  # 因子无变化时设为0
        2 * (candle_df[f'{factor_name}_Raw'] - raw_rolling_min) / (raw_rolling_max - raw_rolling_min) - 1
    )
    
    # 步骤7: 清理临时列
    temp_cols = ['price_change', 'direction', 'direction_change', 'direction_frequency', 'volume_weight', f'{factor_name}_Raw']
    candle_df.drop(columns=temp_cols, inplace=True, errors='ignore')
    
    return candle_df


# 使用说明：
# 1. 因子值解释：
#    - 因子值接近1：表示在成交量较大的情况下，价格方向频繁变化，市场波动剧烈
#    - 因子值接近-1：表示在成交量较大的情况下，价格方向变化较少，市场趋势明显
#    - 因子值在0附近：表示市场处于相对平衡状态
#
# 2. 配置建议：
#    - 短线策略：推荐使用较小周期参数（如10-20），对市场变化更敏感
#    - 长线策略：推荐使用较大周期参数（如30-60），过滤短期噪音
#    - 权重敏感性：默认为1，增大该值会使成交量权重的影响更加明显
#
# 3. 组合使用：
#    - 与趋势类因子（如RSI、MACD）组合，可以提高趋势识别的准确性
#    - 与波动率类因子（如ATR）组合，可以更好地捕捉市场的波动特性
#
# 4. 风险提示：
#    - 极端行情下，因子可能出现异常值，建议配合其他因子或过滤条件使用
#    - 不同币种的特性可能导致因子效果差异，建议根据具体币种特性调整参数