import numpy as np

def signal(candle_df, param, *args):
    """
    CCI v3 魔改版：使用 EWM (指数加权移动平均) 计算
    """
    n = param
    factor_name = args[0]

    # 1. 计算各价格的 EMA
    oma = candle_df['open'].ewm(span=n, adjust=False).mean()
    hma = candle_df['high'].ewm(span=n, adjust=False).mean()
    lma = candle_df['low'].ewm(span=n, adjust=False).mean()
    cma = candle_df['close'].ewm(span=n, adjust=False).mean()
    
    # 2. 计算平滑后的典型价格 (Smoothed TP)
    tp = (oma + hma + lma + cma) / 4
    
    # 3. 计算 TP 的均线
    ma = tp.ewm(span=n, adjust=False).mean()
    
    # 4. 计算平均绝对偏差 (Mean Deviation)
    # 修正逻辑：计算 TP 偏离其均线的程度
    md = (tp - ma).abs().ewm(span=n, adjust=False).mean()
    
    # 5. 计算 CCI
    # 添加 1e-8 防止除以零
    candle_df[factor_name] = (tp - ma) / (md + 1e-8)

    # 6. 处理异常值 (可选，防止 inf 影响排序)
    # candle_df[factor_name] = candle_df[factor_name].replace([np.inf, -np.inf], np.nan)

    return candle_df
