import numpy as np


def signal(*args):
    """
    波动率调整后的 VWAP 偏离率因子。

    Factor = (Close - VWAP_n) / STD(Close, n)
    使用资产波动率来标准化偏离度，放大低波动下的有效信号。
    """
    df = args[0]
    n = args[1] if len(args) >= 2 and args[1] is not None else 20
    factor_name = args[2] if len(args) >= 3 and isinstance(args[2], str) else 'vw_bias'

    # 1. 计算 VWAP_n
    if 'quote_volume' in df.columns and df['quote_volume'].notnull().any():
        amount = df['quote_volume']
    else:
        amount = df['close'] * df['volume']

    # 避免分母为 0
    volume_sum = df['volume'].rolling(n, min_periods=1).sum() + 1e-9
    vwap = amount.rolling(n, min_periods=1).sum() / volume_sum

    # 2. 计算偏离度的分子 (Close - VWAP_n)
    raw_bias_numerator = df['close'] - vwap

    # 3. 计算波动率 (标准差作为新的分母)
    # 使用收盘价在 N 周期内的标准差作为波动率
    volatility = df['close'].rolling(n, min_periods=1).std()

    # 4. 计算最终因子：波动率调整后的偏离度
    # 避免分母为 0
    df[factor_name] = raw_bias_numerator / volatility.replace(0, 1e-9)

    return df