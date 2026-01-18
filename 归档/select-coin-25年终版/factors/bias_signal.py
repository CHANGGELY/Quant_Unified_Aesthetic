def signal(candle_df, param, *args):
    factor_name = args[0]
    
    # 默认参数
    window = 240
    lower_limit = -0.15
    upper_limit = 0
    
    # 解析参数
    # 支持格式：
    # 1. int: 240 (使用默认阈值 -0.15, 0)
    # 2. str: "240,-0.15,0"
    # 3. list/tuple: [240, -0.15, 0]
    if isinstance(param, (int, float)):
        window = int(param)
    elif isinstance(param, str):
        try:
            parts = param.split(',')
            window = int(parts[0])
            if len(parts) > 1:
                lower_limit = float(parts[1])
            if len(parts) > 2:
                upper_limit = float(parts[2])
        except ValueError:
            # 如果解析失败，尝试直接转int
            window = int(param)
    elif isinstance(param, (list, tuple)):
        window = int(param[0])
        if len(param) > 1:
            lower_limit = float(param[1])
        if len(param) > 2:
            upper_limit = float(param[2])

    ma = candle_df["close"].rolling(window, min_periods=1).mean()
    bias = candle_df["close"] / ma - 1

    candle_df[factor_name] = ((bias >= lower_limit) & (bias <= upper_limit)).astype(int)

    return candle_df
