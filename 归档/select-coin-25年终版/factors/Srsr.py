"""SRSR方向动量因子，基于阻力支撑相对强度的市场择时指标

SRSR因子的核心思想是：
- 通过最高价与最低价的线性回归斜率（beta）来量化支撑与阻力的相对强度
- 斜率大表示支撑强于阻力，市场倾向于上涨
- 斜率小则表示阻力强于支撑，市场可能下跌
- 结合方向动量的思想，预测收益率的方向
- 对斜率进行标准化处理得到标准分，提升策略效果

该因子能有效识别市场转折点，具有较强的左侧预测能力，配合趋势确认后可显著提升择时效果
"""
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression


def calculate_rsrs_slope(candle_df, n):
    """
    计算阻力支撑相对强度（RSRS）的斜率
    
    :param candle_df: K线数据
    :param n: 计算周期
    :return: RSRS斜率序列
    """
    # 定义一个函数来计算单个窗口的RSRS斜率
    def _get_slope(window_high, window_low):
        # 当窗口数据不足时返回0
        if len(window_high) < n:
            return 0
        
        # 准备线性回归的自变量和因变量
        X = window_low.values.reshape(-1, 1)  # 最低价作为自变量
        y = window_high.values.reshape(-1, 1)  # 最高价作为因变量
        
        # 执行线性回归
        model = LinearRegression()
        model.fit(X, y)
        
        # 返回斜率
        return model.coef_[0][0]
    
    # 初始化结果序列
    rsrs_slope = pd.Series(0, index=candle_df.index)
    
    # 只对需要的列进行计算，避免非数值类型的问题
    for i in range(n-1, len(candle_df)):
        # 获取当前窗口的最高价和最低价数据
        window_high = candle_df['high'].iloc[i-n+1:i+1]
        window_low = candle_df['low'].iloc[i-n+1:i+1]
        
        # 计算斜率
        rsrs_slope.iloc[i] = _get_slope(window_high, window_low)
    
    # 使用shift(1)避免未来函数
    rsrs_slope = rsrs_slope.shift(1)
    
    return rsrs_slope


def calculate_standardized_rsrs(rsrs_slope, n):
    """
    对RSRS斜率进行标准化处理
    
    :param rsrs_slope: RSRS斜率序列
    :param n: 标准化窗口
    :return: 标准化后的RSRS值
    """
    # 计算滚动均值和标准差
    rolling_mean = rsrs_slope.rolling(window=n, min_periods=1).mean()
    rolling_std = rsrs_slope.rolling(window=n, min_periods=1).std().replace(0, 1e-9)  # 避免除以零
    
    # 计算标准化的RSRS值（Z-score）
    standardized_rsrs = (rsrs_slope - rolling_mean) / rolling_std
    
    # 限制极端值，防止异常波动影响
    standardized_rsrs = standardized_rsrs.clip(-3, 3)
    
    return standardized_rsrs


def calculate_trend_filter(candle_df, ma_period=20):
    """
    计算趋势过滤指标
    
    :param candle_df: K线数据
    :param ma_period: 均线周期，默认为20
    :return: 趋势过滤信号
    """
    # 计算收盘价的移动平均线
    ma = candle_df['close'].rolling(window=ma_period, min_periods=1).mean()
    
    # 当收盘价高于均线时为上涨趋势，否则为下跌趋势
    trend_filter = (candle_df['close'] > ma).astype(int)
    
    return trend_filter


def calculate_directional_rsrs(candle_df, n, std_window=60):
    """
    计算方向动量SRSR因子
    
    :param candle_df: K线数据
    :param n: RSRS计算周期
    :param std_window: 标准化窗口
    :return: 方向动量SRSR因子值
    """
    # 计算RSRS斜率
    rsrs_slope = calculate_rsrs_slope(candle_df, n)
    
    # 对斜率进行标准化处理
    standardized_rsrs = calculate_standardized_rsrs(rsrs_slope, std_window)
    
    # 计算趋势过滤指标
    trend_filter = calculate_trend_filter(candle_df)
    
    # 结合趋势过滤，得到方向动量SRSR因子
    # 当趋势为上涨时，保留原始RSRS值；当趋势为下跌时，调整RSRS值
    directional_rsrs = standardized_rsrs.copy()
    directional_rsrs[trend_filter == 0] *= 0.5  # 下跌趋势时降低RSRS值的影响
    
    # 对最终结果进行标准化，使其范围在[-1, 1]之间
    drsrs_max = directional_rsrs.abs().max()
    if drsrs_max != 0:
        directional_rsrs = directional_rsrs / drsrs_max
    
    return directional_rsrs


def signal(candle_df, param, *args):
    """
    计算SRSR方向动量因子核心逻辑
    
    :param candle_df: 单个币种的K线数据
    :param param: 参数，计算周期，通常为14-20
    :param args: 其他可选参数，args[0]为因子名称
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称
    n = param[0] if len(param) >1 else param  # 计算周期
    m = param[1] if len(param) >1 else 60 # 标准化窗口，越大越平滑，默认60
    
    # 只计算一次RSRS斜率，避免重复计算
    rsrs_slope = calculate_rsrs_slope(candle_df, n)
    
    # 计算标准化的RSRS
    standardized_rsrs = calculate_standardized_rsrs(rsrs_slope, m)
    
    # 计算趋势过滤指标
    trend_filter = calculate_trend_filter(candle_df)
    
    # 直接计算方向动量SRSR因子，避免再次调用calculate_directional_rsrs导致重复计算
    directional_rsrs = standardized_rsrs.copy()
    directional_rsrs[trend_filter == 0] *= 0.5  # 下跌趋势时降低RSRS值的影响
    
    # 对最终结果进行标准化，使其范围在[-1, 1]之间
    drsrs_max = directional_rsrs.abs().max()
    if drsrs_max != 0:
        directional_rsrs = directional_rsrs / drsrs_max
    
    # 存储因子值和中间计算结果
    candle_df[factor_name] = directional_rsrs
    candle_df[f'{factor_name}_slope'] = rsrs_slope
    candle_df[f'{factor_name}_standardized'] = standardized_rsrs
    candle_df[f'{factor_name}_trend_filter'] = trend_filter
    
    return candle_df


# 使用说明：
# 1. SRSR因子值范围在[-1, 1]之间：
#    - SRSR > 0.7: 强烈看多信号，支撑远强于阻力
#    - 0.3 < SRSR <= 0.7: 看多信号，支撑略强于阻力
#    - -0.3 <= SRSR <= 0.3: 中性信号，支撑和阻力相当
#    - -0.7 <= SRSR < -0.3: 看空信号，阻力略强于支撑
#    - SRSR < -0.7: 强烈看空信号，阻力远强于支撑
#
# 2. 该因子具有较强的左侧预测能力，能有效识别市场转折点
#    - 配合趋势确认后可显著提升择时效果
#    - 与其他因子结合使用可提高策略稳定性
#
# 3. 在config.py中的配置示例：
#    factor_list = [
#        ('Srsr', True, 14, 1),        # 标准SRSR因子，14日周期
#        ('Srsr', True, 20, 1),        # SRSR因子，20日周期
#    ]
#
# 4. 参数调优建议：
#    - 周期n增加（如14→20）：因子稳定性提高，但灵敏度降低
#    - 周期n减小（如14→10）：因子灵敏度提高，但噪声增加
#    - 标准化窗口std_window（代码中固定为60）：窗口越大，标准化效果越平滑
#
# 5. 特殊应用：
#    - 在市场出现极端情绪时，该因子可能提前发出反转信号
#    - 可作为趋势跟踪策略的补充，帮助识别潜在的趋势转折
#    - 与成交量指标结合可提高信号质量，确认趋势强度