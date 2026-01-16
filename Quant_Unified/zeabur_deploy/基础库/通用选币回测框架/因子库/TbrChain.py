import numpy as np

def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    # 先计算基础Tbr（同原因子）
    df['Tbr'] = (df['taker_buy_quote_asset_volume'].rolling(n, min_periods=1).sum() /
                 df['quote_volume'].rolling(n, min_periods=1).sum())

    # 计算Tbr的环比：当前n周期Tbr / 前n周期Tbr（反映买盘占比的变化）
    df['TbrChain'] = df['Tbr'] / df['Tbr'].shift(n)
    # 填充空值（前n行无环比数据，用基础Tbr替代）
    df['TbrChain'].fillna(df['Tbr'], inplace=True)

    df[factor_name] = df['TbrChain']
    return df