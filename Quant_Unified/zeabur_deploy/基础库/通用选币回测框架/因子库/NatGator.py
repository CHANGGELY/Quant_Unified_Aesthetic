"""选币策略框架 | 邢不行 | 2024分享会
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
注意：若为小时级别策略，`candle_begin_time` 格式为 2023-11-22 14:00:00；若为日线，则为 2023-11-22。

# ** signal 参数示例 **
- 如果策略配置中 `factor_list` 包含 ('NatGator', True, 3, 1)，则 `param` 为 3，`args[0]` 为 'NatGator_3'。
- 如果策略配置中 `filter_list` 包含 ('NatGator', 3, 'pct:<0.8')，则 `param` 为 3，`args[0]` 为 'NatGator_3'。
"""


"""NatGator因子，基于FuturesTruth杂志全球排名第一的量化策略
核心思路：
1. 计算收盘价与开盘价的价差 (close - open)
2. 计算前一根K线收盘价与当前开盘价的价差 (close[1] - open)
3. 分别对两个价差进行移动平均
4. 计算两个移动平均的差值作为最终信号
"""
import numpy as np


def signal(candle_df, param, *args):
    """
    计算NatGator因子核心逻辑
    :param candle_df: 单个币种的K线数据
    :param param: 移动平均周期参数，例如在 config 中配置 factor_list 为 ('NatGator', True, 3, 1)
    :param args: 其他可选参数，具体用法见函数实现
    :return: 包含因子数据的 K 线数据
    """
    # 获取因子名称和参数
    factor_name = args[0]  # 从额外参数中获取因子名称
    len_period = param  # 移动平均周期，默认为3
    
    # 步骤1：计算当前K线的收盘价与开盘价的价差 (close - open)
    candle_df['diff1'] = candle_df['close'] - candle_df['open']
    
    # 步骤2：计算前一根K线收盘价与当前开盘价的价差 (close[1] - open)
    # 使用shift(1)获取前一根K线的收盘价
    candle_df['close_prev'] = candle_df['close'].shift(1)
    candle_df['diff2'] = candle_df['close_prev'] - candle_df['open']
    
    # 步骤3：分别计算两个价差的移动平均
    # avgB: diff1的移动平均 (买入信号相关)
    candle_df['avgB'] = candle_df['diff1'].rolling(window=len_period, min_periods=1).mean()
    
    # avgS: diff2的移动平均 (卖出信号相关)
    candle_df['avgS'] = candle_df['diff2'].rolling(window=len_period, min_periods=1).mean()
    
    # 步骤4：计算最终的NatGator因子值 (avgB - avgS)
    # 这个差值反映了当前价格动量与前期价格动量的对比
    candle_df[factor_name] = candle_df['avgB'] - candle_df['avgS']
    
    # 清理中间计算列，保持数据框整洁
    candle_df.drop(['diff1', 'diff2', 'close_prev', 'avgB', 'avgS'], axis=1, inplace=True)
    
    return candle_df


