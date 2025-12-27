import numpy as np

def signal(candle_df, param, *args):
    """
    Bolling v1 优化版：连续型 Bollinger Position (Z-Score)
    
    原版 Bolling 是二值化因子 (0/1)，仅当价格处于 [下轨, 中轨] 之间时为 1。
    这种“非黑即白”的切分容易导致参数过拟合（丢失了“偏离程度”的信息）。
    
    优化版改为输出连续的 Z-Score 值：(Close - MA) / STD
    
    数值含义：
    - 0: 价格位于中轨 (MA)
    - -2: 价格位于下轨 (MA - 2*STD)
    - +2: 价格位于上轨 (MA + 2*STD)
    
    优势：
    1. 保留了完整的信息量，反映价格在布林带中的精确位置。
    2. 避免了硬编码阈值 (如 2.0) 带来的过拟合风险。
    3. 可用于排序（long_factor_list）或灵活筛选（filter_list）。
    """
    n = param
    factor_name = args[0]
    
    close = candle_df['close']
    
    # 1. 计算滚动均值 (中轨) 和标准差
    # 保持与原版一致使用 rolling (SMA)，这与 CCI 使用的 ewm (EMA) 有所区别，增加了策略多样性
    mid = close.rolling(n, min_periods=1).mean()
    std = close.rolling(n, min_periods=1).std()
    
    # 2. 计算 Z-Score (即价格距离均线有多少个标准差)
    # 对应原版逻辑：原版筛选的是 [-2, 0] 区间
    # 新版直接输出数值，模型可以自动学习更优的区间或排序
    # + 1e-8 防止标准差为 0 导致除以零
    z_score = (close - mid) / (std + 1e-8)
    
    candle_df[factor_name] = z_score
    
    return candle_df
