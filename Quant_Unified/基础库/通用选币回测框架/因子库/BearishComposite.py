# ** 因子文件功能说明 **
# 1. 因子库中的每个 Python 文件需实现 `signal` 函数，用于计算因子值。
# 2. 除 `signal` 外，可根据需求添加辅助函数，不影响因子计算逻辑。

# ** signal 函数参数与返回值说明 **
# 1. `signal` 函数的第一个参数为 `candle_df`，用于接收单个币种的 K 线数据。
# 2. `signal` 函数的第二个参数用于因子计算的主要参数，具体用法见函数实现。
# 3. `signal` 函数可以接收其他可选参数，按实际因子计算逻辑使用。
# 4. `signal` 函数的返回值应为包含因子数据的 K 线数据。

"""空头综合因子，用于识别适合做空的币种

该因子综合考虑以下空头信号特征：
1. 价格处于超买区域（RSI、CCI指标高位）
2. 价格靠近或突破布林带上轨
3. 短期均线与长期均线形成死叉或空头排列
4. 价格上涨但成交量萎缩（量价背离）
5. 资金流向指标显示资金流出

因子值越高，表示空头信号越强，越适合做空
"""
import numpy as np
import pandas as pd


def calculate_rsi(candle_df, period):
    """计算RSI指标"""
    delta = candle_df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=period, min_periods=1).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period, min_periods=1).mean()
    rs = gain / loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_cci(candle_df, period):
    """计算CCI指标"""
    tp = (candle_df['high'] + candle_df['low'] + candle_df['close']) / 3
    ma = tp.rolling(window=period, min_periods=1).mean()
    md = abs(tp - ma).rolling(window=period, min_periods=1).mean()
    cci = (tp - ma) / (0.015 * md.replace(0, 1e-10))
    return cci


def calculate_bollinger_bands(candle_df, period):
    """计算布林带指标"""
    ma = candle_df['close'].rolling(window=period, min_periods=1).mean()
    std = candle_df['close'].rolling(window=period, min_periods=1).std()
    upper_band = ma + 2 * std
    lower_band = ma - 2 * std
    return ma, upper_band, lower_band


def calculate_volume_price_relationship(candle_df, period):
    """计算量价关系指标"""
    # 计算价格变化率
    price_change = candle_df['close'].pct_change(period).fillna(0)
    # 计算成交量变化率
    volume_change = candle_df['volume'].pct_change(period).fillna(0)
    # 量价背离指标：当价格上涨但成交量萎缩时，值为正
    volume_price_divergence = np.where((price_change > 0) & (volume_change < 0), 
                                      np.abs(price_change) + np.abs(volume_change), 0)
    return pd.Series(volume_price_divergence, index=candle_df.index)


def calculate_moving_average_crossover(candle_df, short_period, long_period):
    """计算均线交叉指标"""
    short_ma = candle_df['close'].rolling(window=short_period, min_periods=1).mean()
    long_ma = candle_df['close'].rolling(window=long_period, min_periods=1).mean()
    # 空头交叉信号：短期均线下穿长期均线
    ma_crossover = np.where(short_ma < long_ma, 1, 0)
    return pd.Series(ma_crossover, index=candle_df.index)


def calculate_funding_fee_bias(candle_df, period):
    """计算资金费率偏差指标"""
    # 资金费率过高可能预示市场过热，适合做空
    funding_fee_ma = candle_df['funding_fee'].rolling(window=period, min_periods=1).mean()
    funding_fee_std = candle_df['funding_fee'].rolling(window=period, min_periods=1).std()
    # 计算Z-score标准化的资金费率
    funding_fee_zscore = (candle_df['funding_fee'] - funding_fee_ma) / funding_fee_std.replace(0, 1e-10)
    return funding_fee_zscore


def calculate_taker_sell_ratio(candle_df, period):
    """计算主动卖盘比例指标"""
    # 计算主动卖盘（假设成交量减去主动买盘即为主动卖盘）
    if 'taker_buy_base_asset_volume' in candle_df.columns:
        taker_sell_volume = candle_df['volume'] - candle_df['taker_buy_base_asset_volume']
        taker_sell_ratio = taker_sell_volume / candle_df['volume'].replace(0, 1e-10)
        # 平滑处理
        taker_sell_ratio_smoothed = taker_sell_ratio.rolling(window=period, min_periods=1).mean()
        return taker_sell_ratio_smoothed
    else:
        # 如果没有主动买盘数据，返回0
        return pd.Series(0, index=candle_df.index)


def signal(candle_df, param, *args):
    """
    计算空头综合因子核心逻辑
    
    :param candle_df: 单个币种的K线数据
    :param param: 参数，例如在 config 中配置 factor_list 为 ('BearishComposite', True, (14, 20, 50), 1)
                  其中 (rsi_period, boll_period, ma_period) 为元组参数
    :param args: 其他可选参数，args[0] 为因子名称
    :return: 包含因子数据的 K 线数据
    """
    # 获取因子名称
    factor_name = args[0] if args else 'BearishComposite'
    
    # 解析参数
    if isinstance(param, tuple) and len(param) >= 3:
        rsi_period, boll_period, ma_period = param[0], param[1], param[2]
    else:
        # 默认参数值
        rsi_period, boll_period, ma_period = 14, 20, 50
    
    # 计算各组件指标
    # 1. RSI超买信号 (RSI值越高，空头信号越强)
    rsi = calculate_rsi(candle_df, rsi_period)
    rsi_bearish = (rsi - 50) / 50  # 归一化到0-1区间
    
    # 2. CCI超买信号 (CCI值越高，空头信号越强)
    cci = calculate_cci(candle_df, rsi_period)
    cci_bearish = np.clip(cci / 300, 0, 1)  # 归一化到0-1区间
    
    # 3. 布林带位置 (越靠近上轨，空头信号越强)
    _, upper_band, _ = calculate_bollinger_bands(candle_df, boll_period)
    bollinger_bearish = np.clip((candle_df['close'] - upper_band / 1.1) / (upper_band * 0.1), 0, 1)
    
    # 4. 均线交叉信号 (短期均线下穿长期均线为1，否则为0)
    ma_cross = calculate_moving_average_crossover(candle_df, rsi_period, ma_period)
    
    # 5. 量价背离信号 (价格上涨但成交量萎缩)
    volume_divergence = calculate_volume_price_relationship(candle_df, 3)
    volume_divergence_normalized = np.clip(volume_divergence, 0, 1)
    
    # 6. 资金费率信号 (资金费率越高，空头信号越强)
    if 'funding_fee' in candle_df.columns:
        funding_fee_signal = calculate_funding_fee_bias(candle_df, rsi_period)
        funding_fee_normalized = np.clip(funding_fee_signal / 3, 0, 1)  # 标准化并截断
    else:
        funding_fee_normalized = pd.Series(0, index=candle_df.index)
    
    # 7. 主动卖盘比例信号 (主动卖盘比例越高，空头信号越强)
    taker_sell_signal = calculate_taker_sell_ratio(candle_df, 3)
    taker_sell_normalized = np.clip((taker_sell_signal - 0.5) * 2, 0, 1)  # 归一化到0-1区间
    
    # 综合所有信号，加权计算最终空头因子值
    # 权重可根据实际效果调整
    weights = {
        'rsi_bearish': 0.2,
        'cci_bearish': 0.2,
        'bollinger_bearish': 0.2,
        'ma_cross': 0.15,
        'volume_divergence': 0.1,
        'funding_fee': 0.1,
        'taker_sell': 0.05
    }
    
    bearish_score = (
        weights['rsi_bearish'] * rsi_bearish +
        weights['cci_bearish'] * cci_bearish +
        weights['bollinger_bearish'] * bollinger_bearish +
        weights['ma_cross'] * ma_cross +
        weights['volume_divergence'] * volume_divergence_normalized +
        weights['funding_fee'] * funding_fee_normalized +
        weights['taker_sell'] * taker_sell_normalized
    )
    
    # 将因子值限制在合理范围内
    bearish_score = np.clip(bearish_score, 0, 1)
    
    # 将结果保存到K线数据中
    candle_df[factor_name] = bearish_score
    
    return candle_df