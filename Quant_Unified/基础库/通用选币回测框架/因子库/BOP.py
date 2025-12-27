# -*- coding:utf-8 -*-
def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    # 步骤1：计算BOP原始值（核心公式）
    # BOP = (收盘价 - 开盘价) / (最高价 - 最低价)，处理分母为0的极端情况
    df['bop_raw'] = df.apply(
        lambda x: (x['close'] - x['open']) / (x['high'] - x['low']) if (x['high'] - x['low']) != 0 else 0,
        axis=1
    )

    # 步骤2：用EMA平滑BOP原始结果（与原CCI/MTM保持一致的平滑规则：span=5，不调整）
    df[factor_name] = df['bop_raw'].ewm(span=5, adjust=False, min_periods=1).mean()

    # 删除中间计算列，保持DataFrame简洁
    del df['bop_raw']

    return df