"""
基础周期因子 | EMA7 的对数斜率（Ema7Slope）

用途：
- 在当前基准周期（如 1H/15m/5m）上，计算 EMA7 的对数斜率，用于判断短均线本身是否在上行/下行。
- 作为长侧过滤：只在 EMA7 斜率 > 0 时允许进入候选；当 EMA7 斜率 <= 0（短均线在走平或下行）时排除。

语义与配置：
- signal(candle_df, param, *args)
  - param：斜率窗口（按“当前基准周期根数”计数），例如 1H 基准下 6 表示最近 6 小时；15m 基准下 24≈6 小时。
  - 过滤示例（长侧）：('Ema7Slope', 6, 'val:>0', True)
  - 过滤示例（短侧）：('Ema7Slope', 6, 'val:<0', True)

实现说明：
- 采用端点差商近似斜率（secant）：slope_t = [ln(EMA7_t) - ln(EMA7_{t-(w-1)})] / (w-1)
- 因子值在“当前K线收盘”落位，下一根开盘执行，无前视偏差。

与其它 EMA 因子搭配：
- 若需确认“EMA7 在 EMA25 上方且开口在扩大”，可同时使用：
  ('EmaDispersionTwoLevel', 0, 'val:>0', True) 与 ('EmaDispersionTwoSlope', 12, 'val:>0', True)
- Ema7Slope 解决“EMA7 本身是否在上行”的问题；开口相关因子解决“相对 EMA25 是否在加强”的问题。
"""

import numpy as np
import pandas as pd


def _calc_log_slope_series(log_series: pd.Series, slope_window: int) -> pd.Series:
    """端点差商近似斜率：slope_t = (log_y[t] - log_y[t-(w-1)]) / (w-1)

    说明：
    - 使用 w>=2；当数据不足时返回 NaN。
    - 该实现与 VwapSlope/EmaDispersionTwoSlope 中的近似一致，数值稳定且高效。
    """
    w = max(2, int(slope_window))
    shifted = log_series.shift(w - 1)
    slope = (log_series - shifted) / (w - 1)
    return slope


def signal(candle_df, param, *args):
    """在基准周期上计算 EMA7 的对数斜率，并写回原时间轴。

    :param candle_df: 单币种K线（需包含 open/high/low/close 与 candle_begin_time）
    :param param: 斜率窗口（按基准周期根数计数，如 6 表示 6 根 1H）
    :param args: args[0] 为因子名称（框架传入），否则默认 'Ema7Slope_{param}'
    :return: candle_df，新增因子列
    """
    factor_name = args[0] if args else f'Ema7Slope_{param}'
    slope_window = int(param) if not isinstance(param, (tuple, list)) else int(param[0])

    # 准备时间轴
    df = candle_df.copy()
    if 'candle_begin_time' not in df.columns:
        raise ValueError('输入数据缺少 candle_begin_time 列')
    df = df.sort_values('candle_begin_time').set_index('candle_begin_time')

    # 计算 EMA7
    ema7 = df['close'].ewm(span=7, adjust=False).mean()

    # 对数斜率（端点差商）
    log7 = np.log(ema7.where(ema7 > 0, np.nan))
    slope7 = _calc_log_slope_series(log7, slope_window)

    # 写入并返回
    candle_df[factor_name] = slope7.values
    return candle_df