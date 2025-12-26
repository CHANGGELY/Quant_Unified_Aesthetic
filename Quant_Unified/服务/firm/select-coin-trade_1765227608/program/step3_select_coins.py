"""
Quant Unified 量化交易系统
step3_select_coins.py
"""
import gc
import time
from datetime import timedelta, datetime

import numpy as np
import pandas as pd

from config import runtime_folder
from core.model.account_config import AccountConfig, load_config
from core.model.strategy_config import StrategyConfig
from core.utils.commons import next_run_time

# pandas相关的显示设置，基础课程都有介绍
pd.set_option('expand_frame_repr', False)  # 当列太多时不换行
pd.set_option('display.unicode.ambiguous_as_wide', True)  # 设置命令行输出时的列对齐功能
pd.set_option('display.unicode.east_asian_width', True)

FACTOR_KLINE_COL_LIST = ['candle_begin_time', 'symbol', 'symbol_type', 'close', '是否交易']


# 选币数据整理 & 选币
def select_coins(account: AccountConfig, is_short=False):
    """
    ** 策略选币 **
    - is_use_spot: True的时候，使用现货数据和合约数据;
    - False的时候，只使用合约数据。所以这个情况更简单

    :param account: config中账户配置的信息
    :return:
    """
    s_time = time.time()
    print('ℹ️选币...')
    # ====================================================================================================
    # 1. 初始化
    # ====================================================================================================
    strategy = account.strategy_short if is_short else account.strategy
    print(f'- 开始选币...')

    # ====================================================================================================
    # 2. 准备选币用数据，并简单清洗
    # ====================================================================================================
    s = time.time()
    # 通过`get_file_path`函数拼接路径
    factor_df = pd.read_pickle(runtime_folder / 'all_factors_df.pkl')
    # 筛选出符合选币条件的数据，包括是否交易，是否在黑名单
    factor_df = factor_df[(factor_df['是否交易'] == 1) & (~factor_df['symbol'].isin(account.black_list))].copy()

    select_scope = strategy.select_scope
    is_spot = select_scope == 'spot'
    if is_spot:
        condition = (factor_df['is_spot'] == 1)
    else:
        condition = (factor_df['is_spot'] == 0)
    factor_df = factor_df.loc[condition, :].copy()

    # 去除无效数据，比如因为rolling长度不够，为空的数据
    factor_df.dropna(subset=strategy.factor_columns, inplace=True)
    factor_df.dropna(subset=['symbol'], how='any', inplace=True)
    factor_df.sort_values(by=['candle_begin_time', 'symbol'], inplace=True)
    factor_df.reset_index(drop=True, inplace=True)

    print(f'- 选币数据准备完成，消耗时间：{time.time() - s:.2f}s')

    # ====================================================================================================
    # 3. 进行纯多或者多空选币，一共有如下几个步骤
    # - 3.0 数据预处理
    # - 3.1 计算目标选币因子
    # - 3.2 前置过滤筛选
    # - 3.3 根据选币因子进行选币
    # - 3.4 根据是否纯多调整币种的权重
    # ====================================================================================================
    """
    3.0 数据预处理
    **实盘专属操作** - 在实盘过程中裁切最后一个周期的数据
    """
    # 裁切当前策略需要的数据长度，保留最后一个周期的交易和因子数据
    max_candle_time = factor_df['candle_begin_time'].max() + pd.to_timedelta(f"1{account.hold_period[-1]}")
    min_candle_time = max_candle_time - pd.to_timedelta(account.hold_period)  # k线本身就是utc时间，不用做时区处理
    factor_df = factor_df[factor_df['candle_begin_time'] >= min_candle_time]
    # 最终选币结果，也只有最后一个周期的

    """
    3.1 计算目标选币因子
    """
    s = time.time()
    # 缓存计算前的列名
    prev_cols = factor_df.columns
    # 计算因子
    result_df = strategy.calc_select_factor(factor_df)
    # 合并新的因子
    factor_df = factor_df[prev_cols].join(result_df[list(set(result_df.columns) - set(prev_cols))])
    print(f'- 选币因子计算耗时：{time.time() - s:.2f}s')

    """
    3.2 前置过滤筛选
    """
    s = time.time()
    long_df, short_df = strategy.filter_before_select(factor_df)
    if is_spot:  # 使用现货数据，则在现货中进行过滤，并选币
        short_df = pd.DataFrame(columns=short_df.columns)
    print(f'- 过滤耗时：{time.time() - s:.2f}s')

    """
    3.3 根据选币因子进行选币
    """
    s = time.time()
    factor_df = select_long_and_short_coin(strategy, long_df, short_df)
    print(f'- 多空选币耗时：{time.time() - s:.2f}s')

    """
    3.4 后置过滤筛选
    """
    factor_df = strategy.filter_after_select(factor_df)
    print(f'[选币] 后置过滤耗时：{time.time() - s:.2f}s')

    """
    3.5 根据是否纯多调整币种的权重
    """
    # 多空模式下，多空各占一半的资金；纯多模式下，多头使用100%的资金
    if account.strategy_short is not None:
        long_weight = account.strategy.cap_weight / (account.strategy.cap_weight + account.strategy_short.cap_weight)
        short_weight = 1 - long_weight
    elif account.strategy.long_select_coin_num == 0 or account.strategy.short_select_coin_num == 0:
        long_weight = 1
        short_weight = 1
    else:
        long_weight = 0.5
        short_weight = 1 - long_weight
    factor_df.loc[factor_df['方向'] == 1, 'target_alloc_ratio'] = factor_df['target_alloc_ratio'] * long_weight
    factor_df.loc[factor_df['方向'] == -1, 'target_alloc_ratio'] = factor_df['target_alloc_ratio'] * short_weight
    factor_df = factor_df[factor_df['target_alloc_ratio'].abs() > 1e-9]  # 去除权重为0的数据

    result_df = factor_df[[*FACTOR_KLINE_COL_LIST, '方向', 'target_alloc_ratio', "is_spot"]].copy()

    if result_df.empty:
        return

    # ====================================================================================================
    # 4. 针对是否启用offset功能，进行处理
    # ====================================================================================================
    # 计算每一个时间戳属于的offset
    cal_offset_base_seconds = 3600 * 24 if strategy.is_day_period else 3600
    reference_date = pd.to_datetime('2017-01-01')
    time_diff_seconds = (result_df['candle_begin_time'] - reference_date).dt.total_seconds()
    offset = (time_diff_seconds / cal_offset_base_seconds).mod(strategy.period_num).astype('int8')
    result_df['offset'] = ((offset + 1 + strategy.period_num) % strategy.period_num).astype('int8')

    # 筛选我们配置需要的offset
    result_df = result_df[result_df['offset'].isin(strategy.offset_list)]

    if result_df.empty:
        return

    # ====================================================================================================
    # 5. 整理生成目标选币结果，并且分配持仓的资金占比 `target_alloc_ratio`
    # ====================================================================================================
    select_result_dict = dict()
    for kline_col in FACTOR_KLINE_COL_LIST:
        select_result_dict[kline_col] = result_df[kline_col]

    select_result_dict['close'] = result_df['close']
    select_result_dict['方向'] = result_df['方向']
    select_result_dict['offset'] = result_df['offset']
    select_result_dict['target_alloc_ratio'] = result_df['target_alloc_ratio'] / len(strategy.offset_list)
    select_result_dict['is_spot'] = result_df['is_spot']
    select_result_df = pd.DataFrame(select_result_dict)
    select_result_df["order_first"] = strategy.order_first

    # ====================================================================================================
    # 6. 缓存到本地文件
    # ====================================================================================================
    file_path = runtime_folder / f'{strategy.name}.pkl'
    select_result_df[
        [*FACTOR_KLINE_COL_LIST, '方向', 'offset', 'target_alloc_ratio', "is_spot", "order_first"]].to_pickle(file_path)

    print(f'💾选币结果数据大小：{select_result_df.memory_usage(deep=True).sum() / 1024 / 1024:.4f} MB')
    print(f'✅完成选币，花费时间：{time.time() - s_time:.3f}秒')
    print()

    return select_result_df


def select_long_and_short_coin(strategy: StrategyConfig, long_df, short_df):
    """
    选币，添加多空资金权重后，对于无权重的情况，减少选币次数
    :param strategy:                策略，包含：多头选币数量，空头选币数量，做多因子名称，做空因子名称，多头资金权重，空头资金权重
    :param long_df:                 多头选币的df
    :param short_df:                空头选币的df
    :return:
    """
    """
    # 做多选币
    """
    long_df = calc_select_factor_rank(long_df, factor_column=strategy.long_factor, ascending=True)

    if int(strategy.long_select_coin_num) == 0:
        # 百分比选币模式
        long_df = long_df[long_df['rank'] <= long_df['总币数'] * strategy.long_select_coin_num].copy()
    else:
        long_df = long_df[long_df['rank'] <= strategy.long_select_coin_num].copy()

    long_df['方向'] = 1
    long_df['target_alloc_ratio'] = 1 / long_df.groupby('candle_begin_time')['symbol'].transform('size')

    """
    # 做空选币
    """
    if not (strategy.select_scope == "spot"):  # 非纯多模式下，要计算空头选币
        short_df = calc_select_factor_rank(short_df, factor_column=strategy.short_factor, ascending=False)

        if strategy.short_select_coin_num == 'long_nums':  # 如果参数是long_nums，则空头与多头的选币数量保持一致
            # 获取到多头的选币数量并整理数据
            long_select_num = long_df.groupby('candle_begin_time')['symbol'].size().to_frame()
            long_select_num = long_select_num.rename(columns={'symbol': '多头数量'}).reset_index()
            # 将多头选币数量整理到short_df
            short_df = short_df.merge(long_select_num, on='candle_begin_time', how='left')
            # 使用多头数量对空头数据进行选币
            short_df = short_df[short_df['rank'] <= short_df['多头数量']].copy()
            del short_df['多头数量']
        else:
            # 百分比选币
            if int(strategy.short_select_coin_num) == 0:
                short_df = short_df[short_df['rank'] <= short_df['总币数'] * strategy.short_select_coin_num].copy()
            # 固定数量选币
            else:
                short_df = short_df[short_df['rank'] <= strategy.short_select_coin_num].copy()

        short_df['方向'] = -1
        short_df['target_alloc_ratio'] = 1 / short_df.groupby('candle_begin_time')['symbol'].transform('size')
        # ===整理数据
        df = pd.concat([long_df, short_df], ignore_index=True)  # 将做多和做空的币种数据合并
    else:
        df = long_df

    df.sort_values(by=['candle_begin_time', '方向'], ascending=[True, False], inplace=True)
    df.reset_index(drop=True, inplace=True)

    del df['总币数'], df['rank_max']

    return df


def calc_select_factor_rank(df, factor_column='因子', ascending=True):
    """
    计算因子排名
    :param df:              原数据
    :param factor_column:   需要计算排名的因子名称
    :param ascending:       计算排名顺序，True：从小到大排序；False：从大到小排序
    :return:                计算排名后的数据框
    """
    # 计算因子的分组排名
    df['rank'] = df.groupby('candle_begin_time')[factor_column].rank(method='min', ascending=ascending)
    df['rank_max'] = df.groupby('candle_begin_time')['rank'].transform('max')
    # 根据时间和因子排名排序
    df.sort_values(by=['candle_begin_time', 'rank'], inplace=True)
    # 重新计算一下总币数
    df['总币数'] = df.groupby('candle_begin_time')['symbol'].transform('size')
    return df


# ======================================================================================
# 选币结果聚合
# ======================================================================================
# region 选币结果聚合
def transfer_swap(select_coin, df_swap):
    """
    将现货中的数据替换成合约数据，主要替换：close
    :param select_coin:     选币数据
    :param df_swap:         合约数据
    :return:
    """
    trading_cols = ['symbol', 'is_spot', 'close', 'next_close']

    # 找到我们选币结果中，找到有对应合约的现货选币
    spot_line_index = select_coin[(select_coin['symbol_swap'] != '') & (select_coin['is_spot'] == 1)].index
    spot_select_coin = select_coin.loc[spot_line_index].copy()

    # 其他的选币，也就是要么已经是合约，要么是现货但是找不到合约
    swap_select_coin = select_coin.loc[select_coin.index.difference(spot_line_index)].copy()

    # 合并合约数据，找到对应的合约（原始数据不动，新增_2）
    # ['candle_begin_time', 'symbol_swap', 'strategy', 'cap_weight', '方向', 'offset', 'target_alloc_ratio']
    spot_select_coin = pd.merge(
        spot_select_coin, df_swap[['candle_begin_time', *trading_cols]],
        left_on=['candle_begin_time', 'symbol_swap'], right_on=['candle_begin_time', 'symbol'],
        how='left', suffixes=('', '_2'))

    # merge完成之后，可能因为有些合约数据上线不超过指定的时间（min_kline_num）,造成合并异常，需要按照原现货逻辑执行
    failed_merge_select_coin = spot_select_coin[spot_select_coin['close_2'].isna()][select_coin.columns].copy()

    spot_select_coin = spot_select_coin.dropna(subset=['close_2'], how='any')
    spot_select_coin['is_spot_2'] = spot_select_coin['is_spot_2'].astype(np.int8)

    spot_select_coin.drop(columns=trading_cols, inplace=True)
    rename_dict = {f'{trading_col}_2': trading_col for trading_col in trading_cols}
    spot_select_coin.rename(columns=rename_dict, inplace=True)

    # 将拆分的选币数据，合并回去
    # 1. 纯合约部分，或者没有合约的现货 2. 不能转换的现货 3. 现货被替换为合约的部分
    select_coin = pd.concat([swap_select_coin, failed_merge_select_coin, spot_select_coin], axis=0)
    select_coin.sort_values(['candle_begin_time', '方向'], inplace=True)

    return select_coin


def aggregate_select_results(account: AccountConfig):
    # 聚合选币结果
    print(f'整理{account.name}选币结果...')
    select_result_path = runtime_folder / 'final_select_results.pkl'
    file_path = runtime_folder / f'{account.strategy.name}.pkl'
    all_select_result_df_list = [pd.read_pickle(file_path)]
    if account.strategy_short is not None:
        file_path = file_path.with_stem(account.strategy_short.name)
        all_select_result_df_list.append(pd.read_pickle(file_path))
    all_select_result_df = pd.concat(all_select_result_df_list, ignore_index=True)
    del all_select_result_df_list
    gc.collect()

    # 筛选一下选币结果，判断其中的 优先下单标记是什么
    cond1 = all_select_result_df['order_first'] == 'swap'  # 优先下单合约
    cond2 = all_select_result_df['is_spot'] == 1  # 当前币种是现货
    if not all_select_result_df[cond1 & cond2].empty:
        # 如果现货部分有对应的合约，我们会把现货比对替换为对应的合约，来节省手续费（合约交易手续费比现货要低）
        all_kline_df = pd.read_pickle(runtime_folder / 'all_factors_df.pkl')
        # 将含有现货的币种，替换掉其中close价格
        df_swap = all_kline_df[(all_kline_df['is_spot'] == 0) & (all_kline_df['symbol_spot'] != '')]
        no_transfer_df = all_select_result_df[~(cond1 & cond2)]
        all_select_result_df = transfer_swap(all_select_result_df[cond1 & cond2], df_swap)
        all_select_result_df = pd.concat([no_transfer_df, all_select_result_df], ignore_index=True)
    all_select_result_df.to_pickle(select_result_path)
    print(f'完成{account.name}结果整理.')
    return all_select_result_df


if __name__ == '__main__':
    # 准备启动时间
    test_time = next_run_time('1h', 0) - timedelta(hours=1)
    if test_time > datetime.now():
        test_time -= timedelta(hours=1)

    # 初始化账户
    account_config = load_config()

    select_coins(account_config)
    if account_config.strategy_short is not None:
        select_coins(account_config, is_short=True)  # 选币

    # 整理选币结果
    select_results = aggregate_select_results(account_config)
