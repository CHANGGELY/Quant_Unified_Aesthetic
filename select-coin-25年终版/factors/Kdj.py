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
- 如果策略配置中 `factor_list` 包含 ('Kdj', True, 9, 1)，则 `param` 为 9，`args[0]` 为 'Kdj_9'。
- 如果策略配置中 `filter_list` 包含 ('Kdj', 9, 'pct:<0.8')，则 `param` 为 9，`args[0]` 为 'Kdj_9'。
"""


"""计算KDJ随机指标

KDJ指标是技术分析中的经典摆动指标，由K值、D值、J值组成：
- K值：快速随机指标，反映价格在一定周期内的相对位置
- D值：K值的平滑移动平均，减少噪音信号
- J值：3*K - 2*D，放大K、D值的差异，提供更敏感的交易信号

计算逻辑：
1. RSV = (收盘价 - N日内最低价) / (N日内最高价 - N日内最低价) * 100
2. K值 = 2/3 * 前一日K值 + 1/3 * 当日RSV
3. D值 = 2/3 * 前一日D值 + 1/3 * 当日K值
4. J值 = 3 * K值 - 2 * D值

参数说明：
- param: KDJ计算周期，通常为9日，可根据策略需求调整
- 周期越短越敏感，但噪音较多；周期越长越平滑，但滞后性增强
"""
import pandas as pd
import numpy as np


def signal(candle_df, param, *args):
    """
    计算KDJ指标核心逻辑
    
    :param candle_df: 单个币种的K线数据
    :param param: KDJ计算周期参数，可以是单个整数(如9)或包含三个参数的元组(如(9,3,3))
    :param args: 其他可选参数，args[0]为因子名称
    :return: 包含KDJ因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称
    
    # 解析参数，支持单个参数或三个参数的元组
    if isinstance(param, (list, tuple)) and len(param) >= 3:
        n = param[0]  # RSV计算周期（通常为9）
        m1 = param[1]  # K值平滑周期（通常为3）
        m2 = param[2]  # D值平滑周期（通常为3）
        
        # 计算K值的权重系数（根据平滑周期）
        k_smooth = 1 / m1
        # 计算D值的权重系数（根据平滑周期）
        d_smooth = 1 / m2
    else:
        # 兼容原有框架的单参数模式，使用默认的平滑周期3
        n = param
        m1 = 3
        m2 = 3
        k_smooth = 1 / 3  # 2/3 * 前一日值 + 1/3 * 当日值
        d_smooth = 1 / 3  # 2/3 * 前一日值 + 1/3 * 当日值
    
    # 计算RSV (Raw Stochastic Value) - 未成熟随机值
    # RSV反映当前收盘价在过去N日价格区间中的相对位置
    low_min = candle_df['low'].rolling(window=n, min_periods=1).min()  # N日内最低价
    high_max = candle_df['high'].rolling(window=n, min_periods=1).max()  # N日内最高价
    
    # 避免除零错误：当最高价等于最低价时，RSV设为50（中性位置）
    rsv = np.where(
        high_max == low_min,
        50,  # 价格无波动时设为中性值
        (candle_df['close'] - low_min) / (high_max - low_min) * 100
    )
    
    # 初始化K、D值序列
    k_values = np.zeros(len(candle_df))
    d_values = np.zeros(len(candle_df))
    
    # 设置初始值：第一个K值和D值都等于第一个RSV值
    k_values[0] = rsv[0] if not np.isnan(rsv[0]) else 50
    d_values[0] = k_values[0]
    
    # 递推计算K值和D值
    # K值 = (1 - k_smooth) * 前一日K值 + k_smooth * 当日RSV（快速线）
    # D值 = (1 - d_smooth) * 前一日D值 + d_smooth * 当日K值（慢速线）
    for i in range(1, len(candle_df)):
        if not np.isnan(rsv[i]):
            k_values[i] = (1 - k_smooth) * k_values[i-1] + k_smooth * rsv[i]
            d_values[i] = (1 - d_smooth) * d_values[i-1] + d_smooth * k_values[i]
        else:
            # 处理缺失值：保持前一个值
            k_values[i] = k_values[i-1]
            d_values[i] = d_values[i-1]
    
    # 计算J值：J = 3*K - 2*D
    # J值是K、D值的加权差值，能够更敏感地反映价格变化
    j_values = 3 * k_values - 2 * d_values
    
    # 将计算结果添加到数据框中
    # candle_df[f'{factor_name}_K'] = k_values  # K值（快速线）
    # candle_df[f'{factor_name}_D'] = d_values  # D值（慢速线）
    # candle_df[f'{factor_name}_J'] = j_values  # J值（超快线）
    
    # 主因子使用J值，因为J值最敏感，适合选币策略
    # J值 > 80 通常表示超买，J值 < 20 通常表示超卖
    candle_df[factor_name] = j_values
    
    return candle_df

# 使用说明：
# 1. KDJ指标参数说明：
#    - 标准参数组合为(9,3,3)，即RSV计算周期9天，K值和D值的平滑周期各3天
#    - 可根据不同市场特性和交易周期调整参数
#
# 2. 参数调优建议：
#    - 缩短RSV周期(n)：增加指标灵敏度，但可能产生更多噪音信号
#    - 延长RSV周期(n)：指标更平滑，但反应可能滞后
#    - 调整平滑周期(m1,m2)：影响K值和D值的平滑程度
#
# 3. 在config.py中的配置示例：
#    # 使用单参数（兼容原框架）
#    factor_list = [
#        ('Kdj', True, 9, 1),  # 标准KDJ，默认使用(9,3,3)参数组合
#    ]
#    
#    # 注意：如果框架支持传递元组参数，可以使用完整的三参数配置
#    # 但需要确认框架是否支持在配置中传递元组类型参数
#    # 如果不支持，可通过自定义参数处理或使用辅助函数实现
#
# 4. J值的使用：
#    - J值 > 100：严重超买，可能回调
#    - J值 < 0：严重超卖，可能反弹
#    - K线从下向上穿过D线（金叉）：买入信号
#    - K线从上向下穿过D线（死叉）：卖出信号
#
# 5. 注意事项：
#    - KDJ指标在震荡市中效果较好，在趋势市中可能产生滞后信号
#    - 建议结合其他指标（如MACD、RSI等）一起使用，提高信号质量