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
- 如果策略配置中 `factor_list` 包含 ('TMV', True, 20, 1)，则 `param` 为 20，`args[0]` 为 'TMV_20'。
- 如果策略配置中 `filter_list` 包含 ('TMV', 20, 'pct:<0.8')，则 `param` 为 20，`args[0]` 为 'TMV_20'。
"""

"""TMV策略因子，结合趋势(Trend)、动量(Momentum)、波动率(Volatility)和成交量(Volume)四个维度

根据微信公众号文章《结合ADX,CCI及MA设计（TMV strategy）一个完美的交易系统》实现

TMV策略使用以下指标组合：
- 凯尔特纳通道(Keltner Channel)：用于识别趋势和波动
- 平均方向移动指数(ADX)：用于衡量趋势强度
- 商品通道指数(CCI)：用于识别动量
- 成交量震荡指标：用于识别成交量异常

本因子将这些指标综合成一个单一的评分，可作为选币策略的权重因子
"""
import pandas as pd
import numpy as np


def calculate_keltner_channel(candle_df, n):
    """
    计算凯尔特纳通道(Keltner Channel)
    - 中轨：基于典型价格的n日简单移动平均线
    - 上轨：中轨 + n日价格区间的简单移动平均线
    - 下轨：中轨 - n日价格区间的简单移动平均线
    
    :param candle_df: K线数据
    :param n: 计算周期
    :return: 包含中轨、上轨、下轨的DataFrame
    """
    # 计算典型价格：(最高价+最低价+收盘价)/3
    typical_price = (candle_df['high'] + candle_df['low'] + candle_df['close']) / 3
    
    # 计算中轨：n日简单移动平均线
    middle_band = typical_price.rolling(window=n, min_periods=1).mean()
    
    # 计算价格区间：最高价-最低价
    range_hl = candle_df['high'] - candle_df['low']
    
    # 计算价格区间的n日简单移动平均线
    range_hl_sma = range_hl.rolling(window=n, min_periods=1).mean()
    
    # 计算上轨和下轨
    upper_band = middle_band + range_hl_sma
    lower_band = middle_band - range_hl_sma
    
    return pd.DataFrame({
        'keltner_middle': middle_band,
        'keltner_upper': upper_band,
        'keltner_lower': lower_band
    })


def calculate_adx(candle_df, n):
    """
    计算平均方向移动指数(ADX)
    
    :param candle_df: K线数据
    :param n: 计算周期
    :return: 包含ADX、DI+、DI-的DataFrame
    """
    # 计算真实波幅TR
    tr1 = candle_df['high'] - candle_df['low']
    tr2 = abs(candle_df['high'] - candle_df['close'].shift(1))
    tr3 = abs(candle_df['low'] - candle_df['close'].shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # 计算方向性移动DM+ 和 DM-
    high_diff = candle_df['high'] - candle_df['high'].shift(1)
    low_diff = candle_df['low'].shift(1) - candle_df['low']
    
    dm_plus = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
    dm_minus = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)
    
    # 计算平滑的TR、DM+、DM-
    tr_smooth = tr.ewm(alpha=1/n, adjust=False).mean()
    dm_plus_smooth = pd.Series(dm_plus).ewm(alpha=1/n, adjust=False).mean()
    dm_minus_smooth = pd.Series(dm_minus).ewm(alpha=1/n, adjust=False).mean()
    
    # 计算方向性指标DI+ 和 DI-
    di_plus = (dm_plus_smooth / tr_smooth) * 100
    di_minus = (dm_minus_smooth / tr_smooth) * 100
    
    # 计算DX（方向性指数）
    dx = abs(di_plus - di_minus) / (di_plus + di_minus) * 100
    dx = dx.replace([np.inf, -np.inf], 0)
    
    # 计算ADX（平均方向性指数）
    adx = dx.ewm(alpha=1/n, adjust=False).mean()
    
    return pd.DataFrame({
        'adx': adx,
        'di_plus': di_plus,
        'di_minus': di_minus
    })


def calculate_cci(candle_df, n):
    """
    计算商品通道指数(CCI)
    
    :param candle_df: K线数据
    :param n: 计算周期
    :return: 包含CCI值的Series
    """
    # 计算典型价格
    typical_price = (candle_df['high'] + candle_df['low'] + candle_df['close']) / 3
    
    # 计算典型价格的n日简单移动平均线
    typical_price_sma = typical_price.rolling(window=n, min_periods=1).mean()
    
    # 计算平均绝对偏差(MAD)
    mad = abs(typical_price - typical_price_sma).rolling(window=n, min_periods=1).mean()
    
    # 计算CCI
    cci = (typical_price - typical_price_sma) / (0.015 * mad)
    cci = cci.replace([np.inf, -np.inf], 0)
    cci = cci.fillna(0)
    
    return cci


def calculate_volume_oscillator(candle_df, n_short, n_long):
    """
    计算成交量震荡指标
    
    :param candle_df: K线数据
    :param n_short: 短期周期
    :param n_long: 长期周期
    :return: 包含成交量震荡值的Series
    """
    # 计算短期和长期成交量移动平均线
    volume_short_sma = candle_df['volume'].rolling(window=n_short, min_periods=1).mean()
    volume_long_sma = candle_df['volume'].rolling(window=n_long, min_periods=1).mean()
    
    # 计算成交量震荡指标
    volume_osc = ((volume_short_sma - volume_long_sma) / volume_long_sma) * 100
    volume_osc = volume_osc.replace([np.inf, -np.inf], 0)
    volume_osc = volume_osc.fillna(0)
    
    return volume_osc


def signal(candle_df, param, *args):
    """
    计算TMV（趋势、动量、波动率、成交量）综合因子核心逻辑
    
    :param candle_df: 单个币种的K线数据
    :param param: 计算周期参数，支持整数或元组格式
    :param args: 其他可选参数，args[0]为因子名称
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称
    
    # 解析参数
    if isinstance(param, tuple):
        # 支持元组格式参数：(主周期, 短期成交量周期, 长期成交量周期, 短期移动平均线周期)
        n = param[0]  # 主计算周期，用于凯尔特纳通道、ADX、CCI
        n_short_vol = param[1] if len(param) > 1 else 5  # 短期成交量周期
        n_long_vol = param[2] if len(param) > 2 else 20  # 长期成交量周期
        n_short_ma = param[3] if len(param) > 3 else 8   # 短期移动平均线周期
    else:
        # 默认参数设置
        n = param  # 主计算周期
        n_short_vol = 5  # 短期成交量周期
        n_long_vol = 20  # 长期成交量周期
        n_short_ma = 8   # 短期移动平均线周期
    
    # 步骤1: 计算凯尔特纳通道
    keltner_df = calculate_keltner_channel(candle_df, n)
    
    # 步骤2: 计算ADX指标
    adx_df = calculate_adx(candle_df, n)
    
    # 步骤3: 计算CCI指标
    cci = calculate_cci(candle_df, n)
    
    # 步骤4: 计算成交量震荡指标
    volume_osc = calculate_volume_oscillator(candle_df, n_short_vol, n_long_vol)
    
    # 步骤5: 计算短期移动平均线
    short_ma = candle_df['close'].rolling(window=n_short_ma, min_periods=1).mean()
    
    # 步骤6: 构建综合评分
    # 1. 趋势评分：基于价格相对于凯尔特纳通道的位置和ADX趋势强度
    trend_score = np.where(
        adx_df['adx'] > 25,  # 有明显趋势
        np.where(
            candle_df['close'] > keltner_df['keltner_middle'],  # 价格在中轨上方
            1.0 + (adx_df['adx'] / 100),  # 正向趋势评分
            -1.0 - (adx_df['adx'] / 100)  # 负向趋势评分
        ),
        0  # 无明显趋势
    )
    
    # 2. 动量评分：基于CCI值的标准化
    # CCI通常在-200到+200之间波动，我们将其标准化到-1到1之间
    momentum_score = np.clip(cci / 200, -1, 1)
    
    # 3. 成交量评分：基于成交量震荡指标的标准化
    # 成交量震荡指标通常在-50到+50之间波动，我们将其标准化到-0.5到+0.5之间
    volume_score = np.clip(volume_osc / 100, -0.5, 0.5)
    
    # 4. 综合TMV评分：加权组合各维度评分
    tmv_score = 0.4 * trend_score + 0.3 * momentum_score + 0.3 * volume_score
    
    # 步骤7: 添加趋势方向辅助指标（类似文章中的颜色编码概念）
    # 当ADX上升且价格收于短期均线上方时，为正向趋势
    # 当ADX上升且价格收于短期均线下方时，为负向趋势
    adx_rising = adx_df['adx'] > adx_df['adx'].shift(1)
    price_above_ma = candle_df['close'] > short_ma
    
    trend_direction = np.where(
        adx_rising,
        np.where(price_above_ma, 1, -1),
        0
    )
    
    # 将计算结果添加到数据框中
    candle_df[f'{factor_name}'] = tmv_score
    candle_df[f'{factor_name}_Trend'] = trend_score
    candle_df[f'{factor_name}_Momentum'] = momentum_score
    candle_df[f'{factor_name}_Volume'] = volume_score
    candle_df[f'{factor_name}_Direction'] = trend_direction
    
    # 添加各指标的原始值作为辅助分析
    candle_df[f'{factor_name}_ADX'] = adx_df['adx']
    candle_df[f'{factor_name}_DI_Plus'] = adx_df['di_plus']
    candle_df[f'{factor_name}_DI_Minus'] = adx_df['di_minus']
    candle_df[f'{factor_name}_CCI'] = cci
    candle_df[f'{factor_name}_Keltner_Middle'] = keltner_df['keltner_middle']
    candle_df[f'{factor_name}_Keltner_Upper'] = keltner_df['keltner_upper']
    candle_df[f'{factor_name}_Keltner_Lower'] = keltner_df['keltner_lower']
    
    return candle_df


# 使用说明：
# 1. 因子值解释：
#    - TMV综合评分范围大致为-2.0到+2.0
#    - 正值表示看多信号，值越大表示看多强度越强
#    - 负值表示看空信号，值越小表示看空强度越强
#    - Trend、Momentum、Volume分量分别表示趋势、动量、成交量维度的评分
#    - Direction值为1表示上升趋势，-1表示下降趋势，0表示无明显趋势
#
# 2. 与其他因子结合使用：
#    - 该因子可以与其他技术指标结合使用，提高选币准确性
#    - 当TMV评分与其他指标方向一致时，信号可信度更高
#
# 3. 在config.py中的配置示例：
#    factor_list = [
#        ('TMV', True, 20, 1),              # 标准TMV，主周期20
#        ('TMV', True, (20, 5, 20, 8), 1),  # 完整参数配置：主周期20，短期成交量周期5，长期成交量周期20，短期MA周期8
#        ('TMV', True, (14, 3, 15, 5), 1),  # 更敏感的参数配置
#    ]
#
# 4. 参数调优建议：
#    - 主周期n：默认为20，可根据交易频率调整
#      * 短线交易：n=10-14
#      * 中线交易：n=20-30
#      * 长线交易：n=50-100
#    - 成交量周期：短期周期通常小于长期周期，如(5,20)、(3,15)等
#    - 短期MA周期：默认为8，可调整为5-10之间的值
#
# 5. 信号确认建议：
#    - 当TMV综合评分 > 0.5且Direction=1时，可考虑买入
#    - 当TMV综合评分 < -0.5且Direction=-1时，可考虑卖出
#    - 结合价格突破凯尔特纳通道、CCI超买超卖等条件使用效果更佳