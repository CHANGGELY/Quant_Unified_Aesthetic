
def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    # 计算主动买入占比因子
    # taker_buy_base_asset_volume: 主动买入的基础资产数量
    # volume: 总交易量（基础资产）
    # 主动买入占比 = 主动买入量 / 总交易量
    df['active_buy_ratio'] = df['taker_buy_base_asset_volume'] / (df['volume'] + 1e-9)

    # 对占比进行滚动窗口处理（可选）
    # 计算n周期内的平均主动买入占比
    df[factor_name] = df['active_buy_ratio'].rolling(
        window=n,
        min_periods=1
    ).mean()

    # 清理临时列
    df.drop('active_buy_ratio', axis=1, inplace=True, errors='ignore')

    return df