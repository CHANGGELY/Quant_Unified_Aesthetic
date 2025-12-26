def signal(*args):
    df = args[0]
    n = args[1]
    factor_name = args[2]

    # 使用标准成交额计算 VWAP，避免 quote_volume 噪音
    df["amount"] = df["close"] * df["volume"]  # 成交额 = 价格 * 成交量
    vwap = (
        df["amount"].rolling(n, min_periods=1).sum()
        / df["volume"].rolling(n, min_periods=1).sum()
    )

    # 使用平滑收盘价，减少偶发 wick 造成的假偏离
    df["smooth_close"] = df["close"].rolling(5, center=True, min_periods=1).median()

    # 趋势增强：只有上涨趋势中偏离才更可靠
    trend = df["close"] / df["close"].rolling(n, min_periods=1).mean()

    # 计算偏离率（但使用平滑价格）
    raw_bias = (df["smooth_close"] - vwap) / vwap

    # 偏离率 * 趋势方向（增强信号稳定性）
    df[factor_name] = raw_bias * trend

    return df
