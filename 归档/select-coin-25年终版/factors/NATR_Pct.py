"""
邢不行™️选币框架
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662


"""
import pandas as pd


def signal(*args):
    """
    计算NATR相对于N日前的变化率

    """
    df = args[0]
    n = args[1]
    factor_name = args[2]

    # 解析参数：param应该是一个包含两个整数的元组或列表
    if isinstance(n, (list, tuple)) and len(n) >= 2:
        N1 = int(n[0])  # NATR计算周期
        N2 = int(n[1])  # shift周期（变化率计算）
    elif isinstance(n, (int, float)):
        # 如果只传入一个参数，使用相同的值
        N1 = int(n)
        N2 = int(n)
    else:
        # 默认值
        N1 = 20
        N2 = 10

    # 1. 计算NATR
    # 计算TR
    tr1 = df['high'] - df['low']
    tr2 = abs(df['high'] - df['close'].shift(1))
    tr3 = abs(df['low'] - df['close'].shift(1))

    # 填充第一个值
    tr2.iloc[0] = tr1.iloc[0]
    tr3.iloc[0] = tr1.iloc[0]

    # TR取最大值
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # 计算ATR
    atr = tr.rolling(window=N1, min_periods=1).mean()


    # 计算移动平均
    mc = df['close'].rolling(window=N1, min_periods=1).mean()

    # 计算NATR
    atr_safe = atr.where(atr > 1e-10)
    natr = (df['close'] - mc) / atr_safe

    # 2. 计算NATR在N2日内的min-max标准化
    # 获取过去N2日内的最小值和最大值
    min_val = natr.rolling(window=N2, min_periods=1).min()
    max_val = natr.rolling(window=N2, min_periods=1).max()

    # 计算min-max标准化
    # 公式: (当前值 - 最小值) / (最大值 - 最小值)
    denominator = max_val - min_val

    # 避免除零错误
    denominator_safe = denominator.where(denominator > 1e-10)
    natr_normalized = (natr - min_val) / denominator_safe
    natr_normalized_shift = natr_normalized.shift(N2)
    natr_change = natr_normalized - natr_normalized_shift

    df[factor_name] = natr_change

    return df