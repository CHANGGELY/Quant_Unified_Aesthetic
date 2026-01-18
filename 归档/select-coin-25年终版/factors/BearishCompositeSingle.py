# ** 因子文件功能说明 **
# 1. 因子库中的每个 Python 文件需实现 `signal` 函数，用于计算因子值。
# 2. 除 `signal` 外，可根据需求添加辅助函数，不影响因子计算逻辑。

"""空头综合因子（单参数版）

通过一个基准周期参数 P（单参数）统一控制各子组件的时间尺度，便于寻优。
保留原因子的语义：综合 RSI/CCI 超买、布林上轨靠近、均线空头排列、价涨量缩、资金费与主动卖盘等信号。

使用：在配置中将因子名改为 'BearishCompositeSingle'，参数传整数或浮点数，例如 24。
例如：('BearishCompositeSingle', True, 24)

与原 BearishComposite 不冲突，原文件保留不动。
"""

import numpy as np
import pandas as pd
from typing import Union


def calculate_rsi(candle_df: pd.DataFrame, period: int) -> pd.Series:
    delta = candle_df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=period, min_periods=1).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period, min_periods=1).mean()
    rs = gain / loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_cci(candle_df: pd.DataFrame, period: int) -> pd.Series:
    tp = (candle_df['high'] + candle_df['low'] + candle_df['close']) / 3
    ma = tp.rolling(window=period, min_periods=1).mean()
    md = abs(tp - ma).rolling(window=period, min_periods=1).mean()
    cci = (tp - ma) / (0.015 * md.replace(0, 1e-10))
    return cci


def calculate_bollinger_bands(candle_df: pd.DataFrame, period: int):
    ma = candle_df['close'].rolling(window=period, min_periods=1).mean()
    std = candle_df['close'].rolling(window=period, min_periods=1).std()
    upper_band = ma + 2 * std
    lower_band = ma - 2 * std
    return ma, upper_band, lower_band


def calculate_volume_price_relationship(candle_df: pd.DataFrame, period: int) -> pd.Series:
    price_change = candle_df['close'].pct_change(period).fillna(0)
    volume_change = candle_df['volume'].pct_change(period).fillna(0)
    # 量价背离指标：当价格上涨但成交量萎缩时，值为正
    volume_price_divergence = np.where((price_change > 0) & (volume_change < 0),
                                       np.abs(price_change) + np.abs(volume_change), 0)
    return pd.Series(volume_price_divergence, index=candle_df.index)


def calculate_moving_average_crossover(candle_df: pd.DataFrame, short_period: int, long_period: int) -> pd.Series:
    short_ma = candle_df['close'].rolling(window=short_period, min_periods=1).mean()
    long_ma = candle_df['close'].rolling(window=long_period, min_periods=1).mean()
    # 空头交叉信号：短期均线下穿长期均线
    ma_crossover = np.where(short_ma < long_ma, 1, 0)
    return pd.Series(ma_crossover, index=candle_df.index)


def calculate_funding_fee_bias(candle_df: pd.DataFrame, period: int) -> pd.Series:
    if 'funding_fee' not in candle_df.columns:
        return pd.Series(0, index=candle_df.index)
    funding_fee_ma = candle_df['funding_fee'].rolling(window=period, min_periods=1).mean()
    funding_fee_std = candle_df['funding_fee'].rolling(window=period, min_periods=1).std()
    funding_fee_zscore = (candle_df['funding_fee'] - funding_fee_ma) / funding_fee_std.replace(0, 1e-10)
    return funding_fee_zscore


def calculate_taker_sell_ratio(candle_df: pd.DataFrame, period: int) -> pd.Series:
    if 'taker_buy_base_asset_volume' in candle_df.columns:
        taker_sell_volume = candle_df['volume'] - candle_df['taker_buy_base_asset_volume']
        taker_sell_ratio = taker_sell_volume / candle_df['volume'].replace(0, 1e-10)
        taker_sell_ratio_smoothed = taker_sell_ratio.rolling(window=period, min_periods=1).mean()
        return taker_sell_ratio_smoothed
    else:
        return pd.Series(0, index=candle_df.index)


def signal(candle_df: pd.DataFrame, param: Union[int, float], *args) -> pd.DataFrame:
    """
    空头综合因子（单参数 P）

    :param candle_df: 单个币种的K线数据
    :param param: 单个参数 P（建议 8–64，默认 24），作为基准周期控制各组件窗口
    :param args: 其他参数，args[0] 为因子名称（可选）
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0] if args else 'BearishCompositeSingle'

    # 解析单参数 P
    try:
        P = int(round(float(param)))
    except Exception:
        P = 24
    P = max(2, P)  # 防止过小

    # 映射各组件周期（基于 P；提升灵敏度版）
    rsi_period = max(3, int(round(P * 0.6)))
    cci_period = max(3, int(round(P * 0.8)))
    boll_period = max(5, int(round(P)))
    short_ma_period = max(3, int(round(P * 0.8)))
    long_ma_period = max(short_ma_period + 1, int(round(P * 2)))
    volume_divergence_period = max(2, int(round(P / 6)))
    taker_sell_period = max(2, int(round(P / 6)))
    funding_period = max(3, int(round(P * 0.7)))

    # 计算各组件指标（更偏向“快速响应”）
    rsi = calculate_rsi(candle_df, rsi_period)
    # 更容易在RSI>50时产生空头分值（提高灵敏度）
    rsi_bearish = np.clip((rsi - 50) / 30, 0, 1)

    cci = calculate_cci(candle_df, cci_period)
    cci_bearish = np.clip(cci / 200, 0, 1)

    # 用标准差Z-Score刻画价格相对均值的偏离，价格>均值+1σ即开始给分
    ma_boll = candle_df['close'].rolling(window=boll_period, min_periods=1).mean()
    std_boll = candle_df['close'].rolling(window=boll_period, min_periods=1).std()
    std_safe = std_boll.replace(0, 1e-10)
    z_close = (candle_df['close'] - ma_boll) / std_safe
    bollinger_bearish = np.clip((z_close - 1.0) / 0.5, 0, 1)  # z>=1开始给分，z>=1.5满分

    # 均线空头信号改为“连续型”：短均线低于长均线且距离越大分值越高（更早感知）
    short_ma = candle_df['close'].rolling(window=short_ma_period, min_periods=1).mean()
    long_ma = candle_df['close'].rolling(window=long_ma_period, min_periods=1).mean()
    ma_distance_ratio = (long_ma - short_ma) / long_ma.replace(0, 1e-10)
    ma_cross_signal = np.clip(ma_distance_ratio / 0.02, 0, 1)  # 距离达到2%满分

    volume_divergence = calculate_volume_price_relationship(candle_df, volume_divergence_period)
    volume_divergence_normalized = np.clip(volume_divergence * 1.5, 0, 1)

    funding_fee_signal = calculate_funding_fee_bias(candle_df, funding_period)
    funding_fee_normalized = np.clip(funding_fee_signal / 2, 0, 1)

    taker_sell_signal = calculate_taker_sell_ratio(candle_df, taker_sell_period)
    taker_sell_normalized = np.clip((taker_sell_signal - 0.5) * 2.5, 0, 1)

    # 权重（提升快响应组件的占比）
    weights = {
        'rsi_bearish': 0.15,
        'cci_bearish': 0.15,
        'bollinger_bearish': 0.25,
        'ma_cross': 0.2,
        'volume_divergence': 0.1,
        'funding_fee': 0.05,
        'taker_sell': 0.1,
    }

    bearish_score = (
        weights['rsi_bearish'] * rsi_bearish +
        weights['cci_bearish'] * cci_bearish +
        weights['bollinger_bearish'] * bollinger_bearish +
        weights['ma_cross'] * ma_cross_signal +
        weights['volume_divergence'] * volume_divergence_normalized +
        weights['funding_fee'] * funding_fee_normalized +
        weights['taker_sell'] * taker_sell_normalized
    )

    bearish_score = np.clip(bearish_score, 0, 1)
    candle_df[factor_name] = bearish_score
    return candle_df