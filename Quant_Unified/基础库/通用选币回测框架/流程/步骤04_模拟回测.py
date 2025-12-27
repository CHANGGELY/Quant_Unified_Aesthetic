"""
Quant Unified 量化交易系统
04_模拟回测.py

功能：
    根据选出的币种模拟投资组合的表现，计算资金曲线。
"""
import time
import pandas as pd

from ..核心.模型.配置 import 回测配置
from ..核心.资金曲线 import 计算资金曲线
from ..核心.工具.路径 import 获取文件路径

# pandas相关的显示设置
pd.set_option('expand_frame_repr', False)
pd.set_option('display.unicode.ambiguous_as_wide', True)
pd.set_option('display.unicode.east_asian_width', True)

_PIVOT_DICT_SPOT_CACHE = None
_PIVOT_DICT_SWAP_CACHE = None


def _读取现货行情透视表():
    global _PIVOT_DICT_SPOT_CACHE
    if _PIVOT_DICT_SPOT_CACHE is None:
        _PIVOT_DICT_SPOT_CACHE = pd.read_pickle(获取文件路径('data', 'market_pivot_spot.pkl'))
    return _PIVOT_DICT_SPOT_CACHE


def _读取合约行情透视表():
    global _PIVOT_DICT_SWAP_CACHE
    if _PIVOT_DICT_SWAP_CACHE is None:
        _PIVOT_DICT_SWAP_CACHE = pd.read_pickle(获取文件路径('data', 'market_pivot_swap.pkl'))
    return _PIVOT_DICT_SWAP_CACHE


def 聚合目标仓位(conf: 回测配置, df_select: pd.DataFrame):
    """
    聚合 target_alloc_ratio
    """
    # 构建candle_begin_time序列
    start_date = df_select['candle_begin_time'].min()
    end_date = df_select['candle_begin_time'].max()
    candle_begin_times = pd.date_range(start_date, end_date, freq=conf.持仓周期类型, inclusive='both')

    # 转换选币数据为透视表
    df_ratio = df_select.pivot_table(
        index='candle_begin_time', columns='symbol', values='target_alloc_ratio', aggfunc='sum')

    # 重新填充为完整的时间序列
    df_ratio = df_ratio.reindex(candle_begin_times, fill_value=0)

    # 多offset的权重聚合 (通过 rolling sum 实现权重在持仓周期内的延续)
    df_spot_ratio = df_ratio.rolling(conf.strategy.hold_period, min_periods=1).sum()

    if conf.strategy_short is not None:
        df_swap_short = df_ratio.rolling(conf.strategy_short.hold_period, min_periods=1).sum()
    else:
        df_swap_short = df_spot_ratio

    return df_spot_ratio, df_swap_short


def 模拟回测(conf: 回测配置, select_results, show_plot=True):
    """
    模拟投资组合表现
    """
    # ====================================================================================================
    # 1. 聚合权重
    # ====================================================================================================
    s_time = time.time()
    print('ℹ️ 开始权重聚合...')
    df_spot_ratio, df_swap_ratio = 聚合目标仓位(conf, select_results)
    print(f'✅ 完成权重聚合，花费时间： {time.time() - s_time:.3f}秒')
    print()

    # ====================================================================================================
    # 2. 根据选币结果计算资金曲线
    # ====================================================================================================
    if conf.is_day_period:
        print(f'🌀 开始模拟日线交易，累计回溯 {len(df_spot_ratio):,} 天...')
    else:
        print(f'🌀 开始模拟交易，累计回溯 {len(df_spot_ratio):,} 小时（~{len(df_spot_ratio) / 24:,.0f}天）...')

    pivot_dict_spot = _读取现货行情透视表()
    pivot_dict_swap = _读取合约行情透视表()

    strategy = conf.strategy
    strategy_short = conf.strategy if conf.strategy_short is None else conf.strategy_short

    # 根据 market 配置决定使用哪个 Ratio 表，另一个置零
    # 这里的逻辑稍微有点硬编码，应该根据实际选币结果里的 is_spot 字段来分流更准确
    # 但原框架是这么做的，先保持一致
    
    if strategy.select_scope == 'spot' and strategy_short.select_scope == 'spot':
        df_swap_ratio = pd.DataFrame(0, index=df_spot_ratio.index, columns=df_spot_ratio.columns)
    elif strategy.select_scope == 'swap' and strategy_short.select_scope == 'swap':
        df_spot_ratio = pd.DataFrame(0, index=df_swap_ratio.index, columns=df_swap_ratio.columns)
        
    # 执行核心回测逻辑
    计算资金曲线(conf, pivot_dict_spot, pivot_dict_swap, df_spot_ratio, df_swap_ratio, show_plot=show_plot)
    print(f'✅ 完成，回测时间：{time.time() - s_time:.3f}秒')
    print()

    return conf.report

# Alias
simulate_performance = 模拟回测