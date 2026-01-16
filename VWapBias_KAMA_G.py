# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd


def _safe_price(df: pd.DataFrame) -> np.ndarray:
    """
    计算 price = quote_volume / volume
    并做工程级安全处理，防止 NaN / Inf 污染
    """
    qv = df['quote_volume'].to_numpy(dtype=np.float64)
    vol = df['volume'].to_numpy(dtype=np.float64)

    price = np.divide(qv, vol, out=np.full_like(qv, np.nan), where=vol != 0)
    price[~np.isfinite(price)] = np.nan
    return price


def _calc_kama(price: np.ndarray, E: int,
               fast_period: int, slow_period: int) -> np.ndarray:
    """
    纯 numpy KAMA 计算，保证：
    - 无前视
    - NaN 不扩散
    """
    n = len(price)

    # ---------- ER ----------
    change = np.empty(n, dtype=np.float64)
    change[:] = 0.0
    if E < n:
        change[E:] = np.abs(price[E:] - price[:-E])

    diff1 = np.abs(price - np.roll(price, 1))
    diff1[0] = 0.0

    volatility = pd.Series(diff1).rolling(E, min_periods=1).sum().to_numpy()
    er = np.divide(change, volatility, out=np.zeros_like(change), where=volatility != 0)

    # ---------- SC ----------
    fast_sc = 2.0 / (fast_period + 1)
    slow_sc = 2.0 / (slow_period + 1)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2

    # ---------- KAMA ----------
    kama = np.empty(n, dtype=np.float64)

    # 初值：取第一个有效 price
    valid_idx = np.where(np.isfinite(price))[0]
    if len(valid_idx) == 0:
        kama[:] = np.nan
        return kama

    first = valid_idx[0]
    kama[:first + 1] = price[first]

    for i in range(first + 1, n):
        if not np.isfinite(price[i]):
            kama[i] = kama[i - 1]
        else:
            kama[i] = kama[i - 1] + sc[i] * (price[i] - kama[i - 1])

    return kama


# =========================
# 单参数接口（框架标准）
# =========================
def signal(*args):
    df = args[0]
    E = int(args[1])
    factor_name = args[2]

    fast_period = 2
    slow_period = 30

    price = _safe_price(df)
    close = df['close'].to_numpy(dtype=np.float64)

    kama = _calc_kama(price, E, fast_period, slow_period)

    factor = np.divide(close - kama, kama,
                       out=np.zeros_like(close),
                       where=np.isfinite(kama) & (kama != 0))

    factor[~np.isfinite(factor)] = 0.0
    df[factor_name] = factor
    return df


# =========================
# 多参数接口（批量选币）
# =========================
def signal_multi_params(df, param_list,
                        fast_period=2, slow_period=30) -> dict:
    ret = {}

    price = _safe_price(df)
    close = df['close'].to_numpy(dtype=np.float64)

    for param in param_list:
        E = int(param)

        kama = _calc_kama(price, E, fast_period, slow_period)

        factor = np.divide(close - kama, kama,
                           out=np.zeros_like(close),
                           where=np.isfinite(kama) & (kama != 0))
        factor[~np.isfinite(factor)] = 0.0

        ret[str(param)] = factor

    return ret
