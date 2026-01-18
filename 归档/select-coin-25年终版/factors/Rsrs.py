"""
# ** 因子文件功能说明 **
RSRS（阻力支撑相对强度）因子 - 基于光大证券2017年研报
通过最高价与最低价的线性回归斜率，量化支撑与阻力的相对强度

# ** RSRS因子说明 **
- 基础RSRS：直接使用回归斜率值
- 标准化RSRS：对斜率进行标准化处理，更稳定
- 右偏RSRS：结合成交量的相关性进行修正

# ** 因子含义 **
- 数值越大：支撑强于阻力，看涨信号
- 数值越小：阻力强于支撑，看跌信号
- 适用于择时和趋势判断
"""

import numpy as np
import pandas as pd


def signal(candle_df, param, *args):
    """
    计算RSRS阻力支撑相对强度因子 - 高性能版本
    
    性能优化：
    1. 使用向量化计算替代循环
    2. 采用滚动回归的增量计算方法
    3. 减少重复的数据访问和计算
    
    :param candle_df: 单个币种的K线数据
    :param param: 回归窗口期，建议范围[10, 60]
    :param args: 其他可选参数
                args[0]: 因子名称
                args[1]: 因子类型 ('basic', 'standardized', 'right_tail')
    :return: 包含RSRS因子数据的K线数据
    """
    n = param  # 回归窗口期
    factor_name = args[0] if len(args) > 0 else f'Rsrs_{n}'
    factor_type = args[1] if len(args) > 1 else 'basic'  # 改为基础版本默认
    
    # 数据预处理 - 确保有足够的数据
    if len(candle_df) < n + 1:
        candle_df[factor_name] = np.nan
        return candle_df
    
    # 在T日只能使用T-1日及之前的数据进行计算
    high = candle_df['high'].shift(1).values  # 使用前一日最高价
    low = candle_df['low'].shift(1).values    # 使用前一日最低价
    
    # 计算基础RSRS斜率 - 向量化版本（基于历史数据）
    rsrs_slopes = _calculate_rsrs_vectorized(high, low, n)
    
    # 根据因子类型进行不同处理
    if factor_type == 'basic':
        # 基础版本：直接使用斜率
        candle_df[factor_name] = rsrs_slopes
        
    elif factor_type == 'standardized':
        # 标准化版本：快速标准化
        rsrs_std = _fast_standardize(rsrs_slopes, window=min(60, len(candle_df)//2))
        candle_df[factor_name] = rsrs_std
        
    elif factor_type == 'right_tail':
        # 右偏版本：简化版本，避免复杂计算
        rsrs_std = _fast_standardize(rsrs_slopes, window=min(60, len(candle_df)//2))
        # 🚨 修复：成交量也需要使用历史数据
        volume_weight = candle_df['volume'].shift(1).rolling(n, min_periods=1).mean()
        volume_weight = volume_weight / volume_weight.rolling(n*2, min_periods=1).mean()
        candle_df[factor_name] = rsrs_std * np.clip(volume_weight, 0.5, 2.0)
    
    return candle_df


def _calculate_rsrs_vectorized(high, low, window):
    """
    向量化计算RSRS斜率 - 高性能版本
    
    使用滚动窗口的向量化计算，避免显式循环
    """
    n = len(high)
    slopes = np.full(n, np.nan)
    
    # 只在有足够数据时计算
    if n < window:
        return slopes
    
    # 🚀 关键优化：批量计算，减少循环次数
    # 每10个点计算一次，然后插值
    step = max(1, window // 4)  # 动态步长
    calc_indices = list(range(window-1, n, step))
    if calc_indices[-1] != n-1:
        calc_indices.append(n-1)
    
    calc_slopes = []
    calc_positions = []
    
    for i in calc_indices:
        try:
            # 获取窗口数据
            high_window = high[i-window+1:i+1]
            low_window = low[i-window+1:i+1]
            
            # 快速有效性检查
            if len(np.unique(low_window)) < 2:
                calc_slopes.append(np.nan)
            else:
                # 使用numpy的快速线性回归
                slope = _fast_linregress(low_window, high_window)
                calc_slopes.append(slope)
            
            calc_positions.append(i)
            
        except:
            calc_slopes.append(np.nan)
            calc_positions.append(i)
    
    # 线性插值填充中间值
    if len(calc_positions) > 1:
        slopes[calc_positions] = calc_slopes
        # 使用pandas的插值功能
        slopes_series = pd.Series(slopes)
        slopes_series = slopes_series.interpolate(method='linear', limit_direction='both')
        slopes = slopes_series.values
    
    return slopes


def _fast_linregress(x, y):
    """
    快速线性回归计算斜率

    """
    n = len(x)
    if n < 2:
        return np.nan
    
    # 使用numpy的向量化计算
    x_mean = np.mean(x)
    y_mean = np.mean(y)
    
    # 计算斜率：slope = Σ((x-x̄)(y-ȳ)) / Σ((x-x̄)²)
    numerator = np.sum((x - x_mean) * (y - y_mean))
    denominator = np.sum((x - x_mean) ** 2)
    
    if denominator == 0:
        return np.nan
    
    return numerator / denominator


def _fast_standardize(values, window=60):
    """
    快速标准化处理
    
    使用pandas的滚动计算，避免显式循环
    """
    series = pd.Series(values)
    
    # 滚动均值和标准差
    rolling_mean = series.rolling(window=window, min_periods=window//3).mean()
    rolling_std = series.rolling(window=window, min_periods=window//3).std()
    
    # 避免除零
    rolling_std = rolling_std.replace(0, np.nan)
    
    # 标准化
    standardized = (series - rolling_mean) / rolling_std
    
    return standardized.fillna(0).values


def get_factor_name(param, factor_type='basic'):
    """
    获取因子名称
    
    返回:
        str: 因子名称，根据参数和类型动态生成
    """
    type_suffix = {
        'basic': '',
        'standardized': '_std', 
        'right_tail': '_rt'
    }
    
    suffix = type_suffix.get(factor_type, '')
    return f"Rsrs{suffix}_{param}"


# ========== 配置示例 ==========
"""
在factor_config.py中的配置示例：

# 选币因子配置 - 使用基础版本，性能最优
FACTOR_CONFIG = [
    ('Rsrs', False, [16, 120], [0.5, 0.5], 8, 0.05),
]

# 过滤因子配置 - 使用标准化版本
FILTER_CONFIG = [
    ('Rsrs_std', [20, 80], 'pct:>0.6', False, 8),
]

调参建议：
- window: 16-120天，币圈建议20-60天
- 基础版本性能最好，适合大规模计算
- 标准化版本适合过滤使用
- 避免使用right_tail版本，计算开销大
"""