
def signal(candle_df, n, *args):
    """
    n小时市场平均上涨比例
    """
    factor_name = args[0]
    # 使用rolling计算
    candle_df[factor_name] = candle_df['market_rise_ratio'].rolling(n).mean()
    return candle_df

# 参考MarketRiseRatio
# # 作为单币种因子配置
# ('MarketRiseRatioRolling', True, 24, 0.8)  # 24小时平均
#
# # 过滤配置
# ('MarketRiseRatioRolling', 24, 'val:>0.4')