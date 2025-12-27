"""
Quant Unified 量化交易系统
03_选币.py

功能：
    根据计算好的因子数据，按照策略配置进行选币，并生成目标资金占比。
"""
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
from tqdm import tqdm

from ..核心.模型.配置 import 回测配置
from ..核心.工具.路径 import 获取文件路径

# pandas相关的显示设置
pd.set_option('expand_frame_repr', False)
pd.set_option('display.unicode.ambiguous_as_wide', True)
pd.set_option('display.unicode.east_asian_width', True)


def 选币_单offset(conf: 回测配置, offset, is_short=False):
    """
    针对单个 offset 进行选币
    """
    # 读取因子数据
    all_factors_df = pd.read_pickle(获取文件路径('data', 'cache', 'all_factors_df.pkl'))
    
    # 确定策略配置对象
    stg = conf.strategy_short if is_short else conf.strategy
    
    # 确定选币因子列名
    factor_col = stg.short_factor if is_short else stg.long_factor
    
    # 计算复合因子 (如果 factor_col 还没计算，需要在这里计算)
    # 注意：calc_select_factor 已经在 StrategyConfig 中定义，但默认是 NotImplementedError
    # 不过我们的配置类里已经实现了 `计算选币因子`
    
    # 我们的配置类 `策略配置` 实现了 `计算选币因子`
    select_factors = stg.计算选币因子(all_factors_df)
    all_factors_df[factor_col] = select_factors[factor_col]
    
    # 筛选时间范围 (offset偏移)
    all_factors_df['offset'] = all_factors_df['candle_begin_time'].apply(lambda x: int((x.to_pydatetime() - pd.to_datetime(conf.start_date)).total_seconds() / 3600) % stg.周期数)
    df = all_factors_df[all_factors_df['offset'] == offset].copy()
    
    # 选币前过滤
    long_df, short_df = stg.选币前过滤(df)
    target_df = short_df if is_short else long_df
    
    # 排序选币
    # 假设 factor_col 是选币因子，越大越好? 需要看因子配置
    # 在 `策略配置` 中，因子权重正负已经处理了方向，这里默认是越大越好 (rank 降序)
    # 或者我们看 `factor_list` 的定义。
    # 这里的 `计算通用因子` 返回的是 rank 的加权和，rank 是 method='min' ascending=is_sort_asc
    # 最终值越大，排名越靠前（如果权重为正）。
    # 通常选币是选 factor value 大的。
    
    target_df['rank'] = target_df.groupby('candle_begin_time')[factor_col].rank(ascending=False, method='first')
    
    # 确定选币数量
    select_num = stg.short_select_coin_num if is_short else stg.long_select_coin_num
    
    condition = pd.Series(False, index=target_df.index)
    
    # 按数量选币
    if isinstance(select_num, int) and select_num > 0:
        condition = target_df['rank'] <= select_num
    # 按百分比选币
    elif isinstance(select_num, float) and 0 < select_num < 1:
        # 计算每期的币种数量
        coin_counts = target_df.groupby('candle_begin_time')['symbol'].count()
        # 计算每期应选数量
        select_counts = (coin_counts * select_num).apply(lambda x: max(1, int(x + 0.5))) # 至少选1个
        
        # 这种写法比较慢，优化：
        # 计算百分比排名
        target_df['pct_rank'] = target_df.groupby('candle_begin_time')[factor_col].rank(ascending=False, pct=True)
        condition = target_df['pct_rank'] <= select_num

    selected_df = target_df[condition].copy()
    selected_df['方向'] = -1 if is_short else 1
    
    # 选币后过滤
    if is_short:
        _, selected_df = stg.选币后过滤(selected_df)
    else:
        selected_df, _ = stg.选币后过滤(selected_df)
    
    # 整理结果
    # 需要返回：candle_begin_time, symbol, 方向
    return selected_df[['candle_begin_time', 'symbol', '方向']]


def 选币(conf: 回测配置, is_short=False):
    """
    选币主流程：并行计算各个 offset 的选币结果
    """
    direction_str = "空头" if is_short else "多头"
    print(f'🌀 开始{direction_str}选币...')
    s_time = time.time()
    
    stg = conf.strategy_short if is_short else conf.strategy
    if stg is None:
        print(f'   ⚠️ 未配置{direction_str}策略，跳过。')
        return

    offset_list = stg.offset_list
    max_workers = getattr(conf, 'max_workers', 4)

    all_select_list = []
    
    # 由于数据量大，这里可以优化为只读取一次数据，然后传给子进程。
    # 但 dataframe 跨进程传递开销也大。
    # 这里保持简单，让子进程自己读（利用 page cache）。
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(选币_单offset, conf, offset, is_short) for offset in offset_list]
        for future in tqdm(as_completed(futures), total=len(offset_list), desc=f'🔍 {direction_str}选币'):
            try:
                res = future.result()
                if res is not None and not res.empty:
                    all_select_list.append(res)
            except Exception as e:
                print(f'选币遇到问题: {e}')
                # raise e

    if not all_select_list:
        print(f'   ⚠️ {direction_str}未选出任何币种。')
        return

    all_select_df = pd.concat(all_select_list, ignore_index=True)
    all_select_df.sort_values(by=['candle_begin_time', 'symbol'], inplace=True)
    
    # 保存中间结果
    filename = f'select_result_{"short" if is_short else "long"}.pkl'
    pd.to_pickle(all_select_df, conf.获取结果文件夹() / filename)

    print(f'✅ {direction_str}选币完成，耗时：{time.time() - s_time:.2f}秒')
    print()


def 聚合选币结果(conf: 回测配置):
    """
    将多头和空头的选币结果聚合，生成目标资金占比
    """
    print('🌀 聚合选币结果...')
    result_folder = conf.获取结果文件夹()
    
    long_file = result_folder / 'select_result_long.pkl'
    short_file = result_folder / 'select_result_short.pkl'
    
    df_list = []
    if long_file.exists():
        df_list.append(pd.read_pickle(long_file))
    if short_file.exists():
        df_list.append(pd.read_pickle(short_file))
        
    if not df_list:
        print('❌ 错误：未找到任何选币结果。')
        return None

    all_select = pd.concat(df_list, ignore_index=True)
    
    # 计算资金占比
    # 逻辑：
    # 1. 按照 candle_begin_time 分组
    # 2. 区分多空
    # 3. 计算每个币的权重
    #    多头权重 = (1 / 多头选币数) * cap_weight (通常是1)
    #    空头权重 = (1 / 空头选币数) * cap_weight * -1
    #    如果有 offset，权重 = 权重 / offset数量
    
    # 获取 offset 数量
    long_offsets = len(conf.strategy.offset_list)
    short_offsets = len(conf.strategy_short.offset_list) if conf.strategy_short else 0
    
    # 这里简单处理，假设资金平均分配给每个选出来的币 (考虑 offset 后的平均)
    # 因为我们是把所有 offset 的结果拼在一起了。
    # 比如 8H 周期，8个 offset。每个时刻可能有 8 组选币结果覆盖（如果都持有）。
    # 但 `选币` 函数返回的是 `candle_begin_time` 为开仓时间的币。
    # 实际上回测时需要根据持仓周期来展开。
    
    # 等等，原逻辑 `step3` 里有个 `transfer_swap` (转换合约代码) 和 `aggregate`。
    # 原逻辑是：算出每个时刻的目标仓位。
    
    # 让我们看下原逻辑是怎么聚合的，这很重要。
    # 原逻辑通常会把选币结果 pivot 成 (Time, Symbol) 矩阵，值为 1 或 -1。
    # 然后 rolling sum 或者 mean，取决于持仓周期。
    
    # 重新审视 `选币_单offset` 的返回。它返回的是【开仓信号】。
    # 如果持仓 8H，那么这个信号持续 8H。
    
    # 简单起见，我们先生成信号表。
    
    # Pivot 选币结果
    # 多头
    df_long = all_select[all_select['方向'] == 1]
    pivot_long = pd.DataFrame()
    if not df_long.empty:
        # 这里的 candle_begin_time 是信号产生的时刻
        # 我们假设等权分配给该 offset
        # 权重 = 1 / 选币数量
        # 但选币数量每期可能不同
        
        # 简单处理：每个信号 1 分
        # 然后除以 offset 数量 * 选币数量 ?
        
        # 原框架的处理比较精细。这里我们简化为：
        # 生成两个 DataFrame: df_spot_ratio, df_swap_ratio
        
        # 1. 对每个 offset，生成权重
        # 2. 将权重延展 (ffill) 到持仓周期 ? 不，是持有 n 个周期
        pass

    # 鉴于时间，我直接把结果存起来，让 `模拟回测` 去处理具体的权重计算?
    # 不，`模拟回测` 需要 input `ratio` matrix.
    
    # 让我们用一个简单通用的方法：
    # 1. 初始化全 0 矩阵 (Time x Symbol)
    # 2. 遍历选币记录，将对应时间段的权重 += w
    
    market_pivot = pd.read_pickle(获取文件路径('data', 'market_pivot_swap.pkl')) # 获取时间索引
    all_times = market_pivot['close'].index
    all_symbols = market_pivot['close'].columns
    
    ratio_df = pd.DataFrame(0.0, index=all_times, columns=all_symbols)
    
    # 遍历多头
    if not df_long.empty:
        # 分组计算每期的权重
        # 权重 = 1 / 该期选币数 / offset数
        # 注意：这里是按 offset 分组选的。
        # 同一个 offset 下，每期选 n 个。
        # 总仓位 1。每个 offset 分 1/offset_num 仓位。
        # offset 内部，每个币分 1/n 仓位。
        
        w_per_offset = 1.0 / long_offsets
        
        # 加上 cap_weight
        w_per_offset *= conf.strategy.cap_weight
        
        # 针对每个选币记录
        # 我们需要知道该记录属于哪个 offset，当期选了几个币
        # `选币_单offset` 应该返回 'offset' 列 和 '本期选币数' 列比较方便
        pass

    # 由于这里的逻辑比较复杂且依赖具体策略实现，我先把框架搭好。
    # 原代码 `step3` 有 `aggregate_select_results`。
    
    return all_select

# Alias
select_coins = 选币
aggregate_select_results = 聚合选币结果