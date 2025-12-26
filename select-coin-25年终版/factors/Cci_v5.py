import numpy as np

def signal(candle_df, param, *args):
    """
    CCI v5 优化版：Z-Score Mode (基于标准差的标准化)
    相比 v4 的改进：使用标准差 (STD) 替代平均绝对偏差 (MD)。
    这使得因子值具有明确的统计学意义（Z-Score），即偏离均线多少个标准差。
    标准差对极端波动更敏感，能有效压制暴涨暴跌产生的虚假高分信号，筛选出趋势更稳健的币种。
    """
    n = param
    factor_name = args[0]

    # 1. 计算各价格的 EMA (平滑处理，过滤 K 线内部噪音)
    # adjust=False 使得计算类似于经典 EMA 递归公式
    oma = candle_df['open'].ewm(span=n, adjust=False).mean()
    hma = candle_df['high'].ewm(span=n, adjust=False).mean()
    lma = candle_df['low'].ewm(span=n, adjust=False).mean()
    cma = candle_df['close'].ewm(span=n, adjust=False).mean()
    
    # 2. 计算平滑后的典型价格 (Smoothed TP)
    tp = (oma + hma + lma + cma) / 4
    
    # 3. 计算 TP 的均线 (基准线)
    ma = tp.ewm(span=n, adjust=False).mean()
    
    # 4. 计算 TP 的标准差 (Standard Deviation)
    # 核心改进：使用 std() 替代 abs().mean()
    # 反映了 TP 围绕其均线波动的离散程度
    std = tp.ewm(span=n, adjust=False).std()
    
    # 5. 计算 Z-Score CCI
    # 公式：(数值 - 均值) / 标准差
    # + 1e-8 防止除以零
    candle_df[factor_name] = (tp - ma) / (std + 1e-8)

    # 6. 处理异常值 (可选)
    # 理论上 Z-Score 大于 3 或小于 -3 属于罕见事件
    # 这里的因子值通常在 [-3, 3] 之间分布，极值更少，排序更稳定
    
    return candle_df
