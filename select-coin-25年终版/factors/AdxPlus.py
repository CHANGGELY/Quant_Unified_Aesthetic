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
- 如果策略配置中 `factor_list` 包含 ('AdxPlus', True, 14, 1)，则 `param` 为 14，`args[0]` 为 'AdxPlus_14'。
- 如果策略配置中 `filter_list` 包含 ('AdxPlus', 14, 'pct:<0.8')，则 `param` 为 14，`args[0]` 为 'AdxPlus_14'。
"""


"""ADX+ (DI+) 上涨趋势强度指标，用于衡量上涨动能的强度"""
import pandas as pd
import numpy as np


def signal(candle_df, param, *args):
    """
    计算ADX+ (DI+) 上涨趋势强度指标
    DI+反映价格上涨动能的强度，数值越高表示上涨趋势越强
    
    计算原理：
    1. 计算真实波幅TR
    2. 计算上涨方向移动DM+
    3. 对TR和DM+进行平滑处理
    4. DI+ = (平滑DM+ / 平滑TR) * 100
    
    :param candle_df: 单个币种的K线数据
    :param param: 计算周期参数，通常为14
    :param args: 其他可选参数，args[0]为因子名称
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称
    n = param  # 计算周期
    
    # 步骤1: 计算真实波幅TR (True Range)
    # TR衡量价格的真实波动幅度，考虑跳空因素
    tr1 = candle_df['high'] - candle_df['low']  # 当日最高价-最低价
    tr2 = abs(candle_df['high'] - candle_df['close'].shift(1))  # 当日最高价-前日收盘价的绝对值
    tr3 = abs(candle_df['low'] - candle_df['close'].shift(1))   # 当日最低价-前日收盘价的绝对值
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # 步骤2: 计算上涨方向移动DM+ (Directional Movement Plus)
    # DM+衡量价格向上突破的动能
    high_diff = candle_df['high'] - candle_df['high'].shift(1)  # 最高价变化
    low_diff = candle_df['low'].shift(1) - candle_df['low']     # 最低价变化（前日-当日）
    
    # 只有当上涨幅度大于下跌幅度且确实上涨时，才记录为正向动能
    dm_plus = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
    
    # 步骤3: 使用Wilder's平滑方法计算平滑TR和DM+
    # Wilder's平滑：类似指数移动平均，但平滑系数为1/n
    tr_smooth = tr.ewm(alpha=1/n, adjust=False).mean()
    dm_plus_smooth = pd.Series(dm_plus).ewm(alpha=1/n, adjust=False).mean()
    
    # 步骤4: 计算DI+ (Directional Indicator Plus)
    # DI+表示上涨趋势的相对强度，范围0-100
    di_plus = (dm_plus_smooth / tr_smooth) * 100
    
    # 将计算结果赋值给因子列
    candle_df[factor_name] = di_plus
    
    return candle_df


# 使用说明：
# 1. DI+数值含义：
#    - DI+ > 25: 上涨趋势较强
#    - DI+ > 40: 强上涨趋势
#    - DI+ < 20: 上涨动能较弱
#
# 2. 交易信号参考：
#    - DI+持续上升：上涨趋势加强，可考虑做多
#    - DI+开始下降：上涨动能减弱，注意风险
#    - DI+与DI-交叉：趋势可能转换
#
# 3. 最佳实践：
#    - 结合ADX使用：ADX>25时DI+信号更可靠
#    - 结合价格形态：在支撑位附近DI+上升信号更强
#    - 避免震荡市：横盘整理时DI+信号容易失效
#
# 4. 在config.py中的配置示例：
#    factor_list = [
#        ('AdxPlus', True, 14, 1),    # 14周期DI+
#        ('AdxPlus', True, 21, 1),    # 21周期DI+（更平滑）
#    ]
#    
#    filter_list = [
#        ('AdxPlus', 14, 'pct:>0.7'),  # 选择DI+排名前30%的币种
#    ]