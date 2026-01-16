import numpy as np
import pandas as pd

def _calc_one_param(df: pd.DataFrame, n: int) -> pd.Series:
    """
    单个 n 参数下的改良 VWAP 偏离因子计算
    返回：因子序列（index 与 df 对齐）
    """
    # 1) 合并滚动计算 VWAP_n 和其他统计量
    tmp = df.copy()

    # 计算成交额的滚动窗口和成交量的滚动窗口
    rolling_vol = tmp['volume'].rolling(n, min_periods=1)
    rolling_amount = (tmp['close'] * tmp['volume']).rolling(n, min_periods=1)

    # 计算 VWAP
    vwap = rolling_amount.sum() / rolling_vol.sum().replace(0, np.nan)

    # 2) 使用“只看过去”的平滑收盘价（无未来函数）
    tmp['smooth_close'] = tmp['close'].rolling(5, min_periods=1).median()

    # 3) 基础偏离率（使用平滑后的价格）
    raw_bias = (tmp['smooth_close'] - vwap) / vwap

    # 4) 计算趋势增强因子
    rolling_trend_ma = tmp['close'].rolling(n, min_periods=1).mean()
    trend = tmp['close'] / rolling_trend_ma
    trend = trend.replace([np.inf, -np.inf], np.nan).fillna(1.0)

    # 5) 计算最终的趋势增强偏离因子
    bias_trend = raw_bias * trend

    # 6) 截断极值，避免异常值影响因子
    bias_trend = bias_trend.clip(lower=-0.5, upper=0.5)

    return bias_trend

def signal(*args):
    """
    单参数版本（邢不行框架标准接口）
    args[0] : df
    args[1] : n（VWAP窗口）
    args[2] : factor_name
    """
    df = args[0]
    n = int(args[1])
    factor_name = args[2]

    df[factor_name] = _calc_one_param(df, n)
    return df

def signal_multi_params(df, param_list) -> dict:
    """
    多参数版本（批量出多个 n 的因子列）
    返回：{ "n值字符串": 因子Series }
    """
    ret = {}
    for param in param_list:
        n = int(param)
        ret[str(param)] = _calc_one_param(df, n)
    return ret
