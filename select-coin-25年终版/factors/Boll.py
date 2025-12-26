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
- 如果策略配置中 `factor_list` 包含 ('Boll', True, 20, 1)，则 `param` 为 20，`args[0]` 为 'Boll_20'。
- 如果策略配置中 `filter_list` 包含 ('Boll', 20, 'pct:<0.8')，则 `param` 为 20，`args[0]` 为 'Boll_20'。
"""

"""Boll布林带指标，用于衡量价格的波动性和相对位置

布林带由三条线组成：
- 中轨：n日移动平均线
- 上轨：中轨 + 2倍标准差
- 下轨：中轨 - 2倍标准差

本因子计算的是(收盘价-下轨)/收盘价，用于衡量价格相对于下轨的位置，可作为选币策略的权重因子
"""
import pandas as pd
import numpy as np


def signal(candle_df, param, *args):
    """
    计算Boll布林带因子核心逻辑
    
    :param candle_df: 单个币种的K线数据
    :param param: 计算周期参数，通常为20
    :param args: 其他可选参数，args[0]为因子名称
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称
    
    # 支持元组参数格式，例如(20, 2)表示周期为20，标准差倍数为2
    if isinstance(param, tuple):
        n = param[0]  # 周期参数
        std_multiplier = param[1] if len(param) > 1 else 2  # 标准差倍数，默认为2
    else:
        n = param  # 计算周期
        std_multiplier = 2  # 默认标准差倍数为2

    # 步骤1: 计算中轨（n日移动平均线）
    # 中轨反映价格的中期趋势
    middle_band = candle_df['close'].rolling(window=n, min_periods=1).mean()

    # 步骤2: 计算标准差
    # 标准差反映价格的波动性
    std = candle_df['close'].rolling(window=n, min_periods=1).std()

    # 步骤3: 计算上轨和下轨
    # 上轨 = 中轨 + std_multiplier倍标准差
    # 下轨 = 中轨 - std_multiplier倍标准差
    upper_band = middle_band + std_multiplier * std
    lower_band = middle_band - std_multiplier * std
    
    # 步骤4: 计算用户需要的因子值：(收盘价-下轨)/收盘价
    # 这个指标表示价格相对于下轨的位置百分比，值越大表示价格离下轨越远
    # 避免收盘价为0导致除零错误
    boll_factor = np.where(
        candle_df['close'] == 0,
        0,  # 收盘价为0时设为0
        (candle_df['close'] - lower_band) / candle_df['close']
    )
    
    # 将计算结果添加到数据框中
    candle_df[f'{factor_name}_Middle'] = middle_band  # 布林带中轨
    candle_df[f'{factor_name}_Upper'] = upper_band    # 布林带上轨
    candle_df[f'{factor_name}_Lower'] = lower_band    # 布林带下轨
    candle_df[factor_name] = boll_factor             # 主因子值
    
    return candle_df


# 使用说明：
# 1. 因子值解释：
#    - 因子值为正：价格在布林带下轨之上
#    - 因子值为负：价格在布林带下轨之下
#    - 因子值越大：价格离下轨越远，可能处于强势状态
#    - 因子值越小：价格接近或跌破下轨，可能处于超卖状态
#
# 2. 与其他因子结合使用：
#    - 该因子可以与RSI、KDJ等超买超卖指标结合，提高选币准确性
#    - 当多个指标同时显示超买或超卖信号时，可信度更高
#
# 3. 在config.py中的配置示例：
#    factor_list = [
#        ('Boll', True, 20, 1),         # 标准布林带，周期20，默认2倍标准差
#        ('Boll', True, (20, 2), 1),    # 显式设置周期20，标准差倍数2
#        ('Boll', True, (20, 1.5), 1),  # 周期20，更窄的布林带（1.5倍标准差）
#        ('Boll', True, (10, 2.5), 1),  # 短周期（10），更宽的布林带（2.5倍标准差）
#    ]
#
# 4. 参数调优建议：
#    - 周期越短（如10）：指标对价格变化越敏感，但可能产生更多噪音信号
#    - 周期越长（如50）：指标更平滑，但反应可能滞后
#    - 标准差倍数越小（如1.5）：布林带越窄，更容易触发信号，但可能产生更多假信号
#    - 标准差倍数越大（如2.5）：布林带越宽，信号越少，但可能错过一些机会
#
# 5. 替代方案建议：
#    - 如果您想更全面地反映价格在布林带中的位置，也可以考虑使用(收盘价-中轨)/(上轨-下轨)的标准化计算方式
#    - 这种方式可以将因子值映射到[-0.5, 0.5]区间，便于不同周期或不同币种之间的比较
#    - 实现方式：candle_df[factor_name] = (candle_df['close'] - middle_band) / (upper_band - lower_band)