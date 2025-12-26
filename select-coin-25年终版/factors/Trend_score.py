"""
选币策略框架 | 邢不行 | 2024分享会
作者: 邢不行
微信: xbx6660

# ** 因子文件功能说明 **
1. 因子库中的每个 Python 文件需实现 `signal` 函数，用于计算因子值。
2. 除 `signal` 外，可根据需求添加辅助函数，不影响因子计算逻辑。

# ** signal 函数参数与返回值说明 **
1. `signal` 函数的第一个参数为 `candle_df`，用于接收单个币种的 K 线数据。
2. `signal` 函数的第二个参数用于因子计算的主要参数，具体用法见函数实现。
3. `signal` 函数可以接收其他可选参数，按实际因子计算逻辑使用。
4. `signal` 函数的返回值应为包含因子数据的 K 线数据。

# ** candle_df 示例 **
    candle_begin_time         symbol      open      high       low     close       volume  quote_volume  trade_num  taker_buy_base_asset_volume  taker_buy_quote_asset_volume  funding_fee   first_candle_time  是否交易
0          2023-11-22  1000BONK-USDT  0.004780  0.004825  0.004076  0.004531  12700997933  5.636783e+07     320715                   6184933232                  2.746734e+07     0.001012 2023-11-22 14:00:00         1
1          2023-11-23  1000BONK-USDT  0.004531  0.004858  0.003930  0.004267  18971334686  8.158966e+07     573386                   8898242083                  3.831782e+07     0.001634 2023-11-22 14:00:00         1
2          2023-11-24  1000BONK-USDT  0.004267  0.004335  0.003835  0.004140  17168511399  6.992947e+07     475254                   7940993618                  3.239266e+07     0.005917 2023-11-22 14:00:00         1

# ** signal 参数示例 **
- 如果策略配置中 `factor_list` 包含 ('QuoteVolumeMean', True, 7, 1)，则 `param` 为 7，`args[0]` 为 'QuoteVolumeMean_7'。
- 如果策略配置中 `filter_list` 包含 ('QuoteVolumeMean', 7, 'pct:<0.8')，则 `param` 为 7，`args[0]` 为 'QuoteVolumeMean_7'。
"""


"""trend_score因子，计算趋势评分：年化收益率 × R平方"""
import numpy as np
import pandas as pd


def signal(candle_df, param, *args):
    """
    计算因子核心逻辑
    :param candle_df: 单个币种的K线数据
    :param param: 参数，例如在 config 中配置 factor_list 为 ('QuoteVolumeMean', True, 7, 1)
    :param args: 其他可选参数，具体用法见函数实现
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称

    # 对数价格
    period = param
    y = np.log(candle_df['close'])
    
    # 检查数据长度是否足够
    if len(y) < period:
        # 数据不足，返回全NaN的因子列
        candle_df[factor_name] = np.nan
        return candle_df
    
    windows = np.lib.stride_tricks.sliding_window_view(y, window_shape=period)
    x = np.arange(period)

    # 预计算固定值
    n = period
    sum_x = x.sum()
    sum_x2 = (x ** 2).sum()
    denominator = n * sum_x2 - sum_x ** 2
    
    # 滑动窗口统计量
    sum_y = windows.sum(axis=1)
    sum_xy = (windows * x).sum(axis=1)
    
    # 计算回归系数
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n

    # 计算收益率趋势强度
    # 优化1: 不进行年化转换，直接使用对数价格斜率作为趋势强度指标
    # 对数价格的斜率已经反映了单位时间内的价格变化率
    
    # 优化2: 使用动态缩放而非硬性截断，避免因子值重复
    # 对斜率应用温和的非线性转换，保留更多原始信息
    trend_strength = slope * 100  # 放大100倍以便观察，但不过度
    
    # 使用自然对数的方式平滑极端值，但不完全限制范围
    # 这种方法比硬性截断保留了更多原始数据的差异
    trend_strength = np.sign(trend_strength) * np.log1p(np.abs(trend_strength))
    
    # 计算R平方
    y_pred = slope[:, None] * x + intercept[:, None]
    residuals = windows - y_pred
    ss_res = np.sum(residuals ** 2, axis=1)
    sum_y2 = np.sum(windows ** 2, axis=1)
    ss_tot = sum_y2 - (sum_y ** 2) / n
    r_squared = 1 - (ss_res / ss_tot)
    r_squared = np.nan_to_num(r_squared, nan=0.0)
    
    # 计算综合评分
    # 优化3: 将趋势强度与R平方结合，反映趋势的方向、强度和统计显著性
    # r_squared反映了线性拟合的好坏，trend_strength反映了趋势方向和强度
    # 两者相乘既考虑了趋势的统计显著性，又保留了趋势的方向信息
    score = trend_strength * r_squared
    
    # 最终缩放，确保数值在合理范围内
    # 由于前面已经使用log1p平滑了极端值，这里只需要简单缩放即可
    score = score * 10
    
    # 对齐原始序列长度并添加到candle_df中
    full_score = pd.Series(index=candle_df.index, dtype=float)
    full_score.iloc[period-1:] = score
    
    # 将因子添加到candle_df中
    candle_df[factor_name] = full_score
    
    return candle_df
