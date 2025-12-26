import numpy as np


def signal(candle_df, n, *args):
    """
    市场成交量增长因子
    计算当前市场总成交量相对n小时前的增长率
    """
    factor_name = args[0]  # 获取因子名称


    # 计算n小时前的市场总成交量
    prev_volume = candle_df['market_total_volume'].shift(n)


    # 计算成交量增长率
    volume_growth = (candle_df['market_total_volume'] - prev_volume) / prev_volume


    # 处理除零和无效值
    volume_growth = volume_growth.replace([np.inf, -np.inf], np.nan)
    volume_growth = volume_growth.fillna(0)


    # 赋值给因子列
    candle_df[factor_name] = volume_growth


    return candle_df