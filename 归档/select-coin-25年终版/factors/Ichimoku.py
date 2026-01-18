"""邢不行™️选币框架
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662

未经授权，不得复制、修改、或使用本代码的全部或部分内容。仅限个人学习用途，禁止商业用途。

Author: 邢不行
--------------------------------------------------------------------------------

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
- 如果策略配置中 `factor_list` 包含 ('Ichimoku', True, (9, 26, 52), 1)，则 `param` 为 (9, 26, 52)，`args[0]` 为 'Ichimoku_9_26_52'。
- 如果策略配置中 `filter_list` 包含 ('Ichimoku', (9, 26, 52), 'pct:<0.8')，则 `param` 为 (9, 26, 52)，`args[0]` 为 'Ichimoku_9_26_52'。
"""

"""Ichimoku一目云图指标，用于综合判断市场趋势、支撑阻力和买卖信号

一目云图由五条线组成：
- 转换线（Tenkan-sen）：(短周期最高价 + 短周期最低价) / 2
- 基准线（Kijun-sen）：(中周期最高价 + 中周期最低价) / 2
- 先行带A（Senkou Span A）：(转换线 + 基准线) / 2，向前移动中周期天数
- 先行带B（Senkou Span B）：(长周期最高价 + 长周期最低价) / 2，向前移动中周期天数
- 延迟线（Chikou Span）：当前收盘价，向后移动中周期天数

本因子计算的是价格相对于云区的位置以及线与线之间的交叉关系，可作为选币策略的趋势判断和买卖信号因子
"""
import pandas as pd
import numpy as np


def signal(candle_df, param, *args):
    """
    计算Ichimoku一目云图因子核心逻辑
    
    :param candle_df: 单个币种的K线数据
    :param param: 计算周期参数，默认格式为(短周期, 中周期, 长周期)，通常为(9, 26, 52)
    :param args: 其他可选参数，args[0]为因子名称
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称
    
    # 支持不同参数格式
    if isinstance(param, tuple) and len(param) >= 3:
        tenkan_period = param[0]    # 转换线周期，默认9
        kijun_period = param[1]     # 基准线周期，默认26
        senkou_period = param[2]    # 先行带B周期，默认52
    elif isinstance(param, tuple) and len(param) == 2:
        tenkan_period = param[0]    # 转换线周期
        kijun_period = param[1]     # 基准线周期
        senkou_period = kijun_period * 2  # 先行带B周期默认为基准线周期的2倍
    else:
        # 如果只提供一个参数，则使用该参数作为基准线周期，其他周期按比例调整
        kijun_period = param
        tenkan_period = int(kijun_period / 2.89)  # 9 ≈ 26 / 2.89
        senkou_period = kijun_period * 2  # 52 = 26 * 2

    # 步骤1: 计算转换线（Tenkan-sen）
    # 转换线反映短期价格趋势，类似短周期的平均价格
    high_tenkan = candle_df['high'].rolling(window=tenkan_period, min_periods=1).max()
    low_tenkan = candle_df['low'].rolling(window=tenkan_period, min_periods=1).min()
    tenkan_sen = (high_tenkan + low_tenkan) / 2

    # 步骤2: 计算基准线（Kijun-sen）
    # 基准线反映中期价格趋势，是重要的支撑阻力位
    high_kijun = candle_df['high'].rolling(window=kijun_period, min_periods=1).max()
    low_kijun = candle_df['low'].rolling(window=kijun_period, min_periods=1).min()
    kijun_sen = (high_kijun + low_kijun) / 2

    # 步骤3: 计算先行带A（Senkou Span A）
    # 先行带A是云区的上边界（若为上升趋势）或下边界（若为下降趋势）
    senkou_span_a = (tenkan_sen + kijun_sen) / 2
    # 向前移动kijun_period天
    senkou_span_a_shifted = senkou_span_a.shift(kijun_period)

    # 步骤4: 计算先行带B（Senkou Span B）
    # 先行带B是云区的下边界（若为上升趋势）或上边界（若为下降趋势）
    high_senkou = candle_df['high'].rolling(window=senkou_period, min_periods=1).max()
    low_senkou = candle_df['low'].rolling(window=senkou_period, min_periods=1).min()
    senkou_span_b = (high_senkou + low_senkou) / 2
    # 向前移动kijun_period天
    senkou_span_b_shifted = senkou_span_b.shift(kijun_period)

    # 步骤5: 计算延迟线（Chikou Span）
    # 延迟线用于确认价格趋势和支撑阻力位
    chikou_span = candle_df['close'].shift(-kijun_period)

    # 步骤6: 计算交易信号因子值
    # 创建多种常用的一目云图交易信号
    
    # 信号1: 价格相对于云区的位置
    # 值为1表示价格在云区之上（牛市），值为-1表示价格在云区之下（熊市）
    cloud_position = np.where(
        candle_df['close'] > senkou_span_a_shifted, 1,
        np.where(candle_df['close'] < senkou_span_b_shifted, -1, 0)
    )
    
    # 信号2: 转换线与基准线的交叉
    # 值为1表示转换线上穿基准线（金叉买入信号），值为-1表示下穿（死叉卖出信号）
    line_cross = np.where(
        tenkan_sen > kijun_sen, 1,
        np.where(tenkan_sen < kijun_sen, -1, 0)
    )
    
    # 信号3: 云区颜色
    # 值为1表示云区看涨（A在B之上），值为-1表示云区看跌（A在B之下）
    cloud_color = np.where(
        senkou_span_a_shifted > senkou_span_b_shifted, 1,
        np.where(senkou_span_a_shifted < senkou_span_b_shifted, -1, 0)
    )
    
    # 主因子值: 综合以上信号，使用加权平均
    # 可以根据策略需求调整各信号的权重
    ichimoku_factor = (cloud_position * 0.4 + line_cross * 0.3 + cloud_color * 0.3)
    
    # 将计算结果添加到数据框中
    candle_df[f'{factor_name}_Tenkan'] = tenkan_sen  # 转换线
    candle_df[f'{factor_name}_Kijun'] = kijun_sen    # 基准线
    candle_df[f'{factor_name}_SenkouA'] = senkou_span_a_shifted  # 先行带A
    candle_df[f'{factor_name}_SenkouB'] = senkou_span_b_shifted  # 先行带B
    candle_df[f'{factor_name}_Chikou'] = chikou_span  # 延迟线
    candle_df[f'{factor_name}_CloudPos'] = cloud_position  # 价格相对于云区位置
    candle_df[f'{factor_name}_LineCross'] = line_cross  # 线交叉信号
    candle_df[f'{factor_name}_CloudColor'] = cloud_color  # 云区颜色信号
    candle_df[factor_name] = ichimoku_factor  # 主因子值
    
    return candle_df


# 使用说明：
# 1. 因子值解释：
#    - 主因子值范围：[-1, 1]
#    - 因子值越接近1：越强的看涨信号
#    - 因子值越接近-1：越强的看跌信号
#    - 因子值在0附近：市场趋势不明确，可能处于盘整状态
#
# 2. 核心交易信号：
#    - 转换线上穿基准线（金叉）+ 价格在云区之上：强烈买入信号
#    - 转换线下穿基准线（死叉）+ 价格在云区之下：强烈卖出信号
#    - 价格从云区下方向上突破云区：可能的趋势反转（看涨）
#    - 价格从云区上方向下突破云区：可能的趋势反转（看跌）
#
# 3. 在config.py中的配置示例：
#    factor_list = [
#        ('Ichimoku', True, (9, 26, 52), 1),        # 标准参数配置
#        ('Ichimoku', True, (7, 20, 40), 1),        # 更敏感的短周期配置
#        ('Ichimoku', True, (12, 30, 60), 1),       # 更平滑的长周期配置
#    ]
#
# 4. 参数调优建议：
#    - 短周期(tenkan_period)：通常为中周期的1/3左右，数值越小越敏感
#    - 中周期(kijun_period)：核心参数，决定指标的整体敏感度
#    - 长周期(senkou_period)：通常为中周期的2倍，影响云区的宽度
#    - 加密货币市场波动较大，建议使用较短的周期参数以提高敏感度
#
# 5. 与其他因子结合使用：
#    - 与RSI结合：避免在超买超卖区域追涨杀跌
#    - 与MACD结合：确认趋势强度和方向
#    - 与成交量指标结合：验证突破的有效性
#
# 6. 注意事项：
#    - 一目云图在趋势明显的市场中效果最佳，在震荡市场中可能产生较多假信号
#    - 云区的厚度反映了市场的波动性，厚云区意味着强支撑/阻力
#    - 延迟线与历史价格的关系也是重要的确认信号
#    - 本实现中，云区前移可能导致最后kijun_period个数据点无法计算完整的云区