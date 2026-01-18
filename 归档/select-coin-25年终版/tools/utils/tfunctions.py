# -*- coding: utf-8 -*-
"""
邢不行｜策略分享会
选币策略框架𝓟𝓻𝓸

版权所有 ©️ 邢不行
微信: xbx1717

本代码仅供个人学习使用，未经授权不得复制、修改或用于商业用途。

Author: 邢不行
"""
import os
import time
from functools import reduce
from itertools import combinations
from pathlib import Path
from typing import List, Union

import numpy as np
import pandas as pd


def _calculate_group_returns(df: pd.DataFrame, factor_name: str, bins: int = 5):
    """分组收益计算内部函数"""

    # 因子排序
    df['total_coins'] = df.groupby('candle_begin_time')['symbol'].transform('size')
    valid_df = df.copy()

    valid_df['rank'] = valid_df.groupby('candle_begin_time')[factor_name].rank(method='first')
    labels = [f'第{i}组' for i in range(1, bins + 1)]

    def assign_group(x: pd.Series):
        n = len(x)
        if n == 0:
            return pd.Series([], index=x.index, dtype=object)

        x_nonnull = x.dropna()
        if x_nonnull.empty:
            return pd.Series([labels[0]] * n, index=x.index)

        nunique = x_nonnull.nunique()
        q = min(bins, nunique, len(x_nonnull))
        if q <= 1:
            return pd.Series([labels[0]] * n, index=x.index)

        local_labels = labels[:q]
        try:
            cats = pd.qcut(x_nonnull, q=q, labels=local_labels, duplicates="drop")
        except ValueError:
            return pd.Series([labels[0]] * n, index=x.index)

        out = pd.Series(labels[0], index=x.index, dtype=object)
        out.loc[x_nonnull.index] = cats.astype(object)
        return out

    valid_df['groups'] = valid_df.groupby('candle_begin_time')['rank'].transform(assign_group)

    # 计算收益
    valid_df['ret_next'] = valid_df['next_close'] / valid_df['close'] - 1
    group_returns = valid_df.groupby(['candle_begin_time', 'groups'])['ret_next'].mean().to_frame()
    group_returns.reset_index('groups', inplace=True)
    group_returns['groups'] = group_returns['groups'].astype(str)

    return labels, group_returns


def group_analysis(df: pd.DataFrame, factor_name: str, bins: int = 5):
    """
    :param df: 包含分析数据的DataFrame
    :param factor_name: 要分析的因子名称
    :param bins: 分组数量，0表示不分析
    :param method: 分箱方法，'quantile'（分位数）或'cut'（等宽分箱）
    :raises ValueError: 输入数据不符合要求时抛出
    """
    # 验证输入数据
    required_columns = ['candle_begin_time', 'symbol', 'close', 'next_close']
    if not all(col in df.columns for col in required_columns):
        missing = [col for col in required_columns if col not in df.columns]
        raise ValueError(f"输入数据缺少必要列: {missing}")

    labels, group_returns = _calculate_group_returns(df, factor_name, bins=bins)

    # 分组整合
    group_returns = group_returns.reset_index()
    group_returns = pd.pivot(group_returns,
                             index='candle_begin_time',
                             columns='groups',
                             values='ret_next')
    group_returns = group_returns.reindex(columns=labels)
    group_curve = (group_returns + 1).cumprod()
    group_curve = group_curve[labels]

    first_bin_label = labels[0]
    last_bin_label = labels[-1]

    long_ret = group_returns[last_bin_label]
    short_ret = -group_returns[first_bin_label]

    group_curve['多头组合净值'] = (long_ret + 1).cumprod()
    group_curve['空头组合净值'] = (short_ret + 1).cumprod()

    if group_curve[first_bin_label].iloc[-1] > group_curve[last_bin_label].iloc[-1]:
        ls_ret = (group_returns[first_bin_label] - group_returns[last_bin_label]) / 2
    else:
        ls_ret = (group_returns[last_bin_label] - group_returns[first_bin_label]) / 2

    group_curve['多空净值'] = (ls_ret + 1).cumprod()
    group_curve = group_curve.fillna(method='ffill')
    bar_df = group_curve.iloc[-1].reset_index()
    bar_df.columns = ['groups', 'asset']

    return group_curve, bar_df, labels


def coins_difference_all_pairs(root_path: Union[str, Path], strategies_list: List[str]):
    """计算所有策略两两之间的选币相似度详细结果"""
    root_path = Path(root_path)

    # 读取所有策略的选币结果，并转换为按时间点的集合
    print("开始读取策略选币结果")
    strategies = {}
    for strategy in strategies_list:
        s_path = os.path.join(root_path, f'data/回测结果/{strategy}/final_select_results.pkl')
        s = pd.read_pickle(s_path)
        if s.empty:
            raise ValueError(f"{strategy}对应选币结果为空，请检查数据")
        s_grouped = s.groupby('candle_begin_time')['symbol'].apply(set).rename(strategy)
        strategies[strategy] = s_grouped

    # 合并所有策略的数据，使用outer join确保包含所有时间点
    df = pd.DataFrame(index=pd.Index([], name='candle_begin_time'))
    for strategy, s in strategies.items():
        df = df.join(s.rename(strategy), how='outer')
    df = df.reset_index()

    # 生成所有两两策略组合
    strategy_pairs = list(combinations(strategies_list, 2))
    results = []

    for strat1, strat2 in strategy_pairs:
        print(f"正在分析{strat1}和{strat2}之间的相似度")

        # 提取策略对数据
        pair_df = df[['candle_begin_time', strat1, strat2]].copy()

        # 考虑到策略回测时间不同，去除nan值
        pair_df = pair_df.dropna()

        if pair_df.empty:
            print(f'🔔 {strat1}和{strat2} 回测时间无交集，需要核实策略回测config')
            results.append((strat1, strat2, np.nan))
            continue

        # 计算交集及选币数量
        pair_df['交集'] = pair_df.apply(lambda x: x[strat1] & x[strat2], axis=1)
        pair_df[f'{strat1}选币数量'] = pair_df[strat1].apply(len)
        pair_df[f'{strat2}选币数量'] = pair_df[strat2].apply(len)
        pair_df['重复选币数量'] = pair_df['交集'].apply(len)

        # 计算相似度（处理分母为零的情况）
        def calc_similarity(row, base_strat, other_strat):
            base_count = row[f'{base_strat}选币数量']
            other_count = row[f'{other_strat}选币数量']
            if base_count == 0:
                return 1.0 if other_count == 0 else np.nan
            return row['重复选币数量'] / base_count

        pair_df[f'相似度_基于{strat1}'] = pair_df.apply(
            lambda x: calc_similarity(x, strat1, strat2), axis=1)
        pair_df[f'相似度_基于{strat2}'] = pair_df.apply(
            lambda x: calc_similarity(x, strat2, strat1), axis=1)
        similarity = np.nanmean((pair_df[f'相似度_基于{strat1}'] + pair_df[f'相似度_基于{strat2}']) / 2)

        results.append((strat1, strat2, similarity))

    return results


def curve_difference_all_pairs(root_path: Union[str, Path], strategies_list: List[str]) -> pd.DataFrame:
    """获取所有策略资金曲线结果"""
    root_path = Path(root_path)

    # 读取所有策略的资金曲线结果，并转换为按时间点的集合
    print("开始读取策略资金曲线")
    strategies = {}
    for strategy in strategies_list:
        s_path = os.path.join(root_path, f'data/回测结果/{strategy}/资金曲线.csv')
        s = pd.read_csv(s_path, encoding='utf-8-sig', parse_dates=['candle_begin_time'])
        if s.empty:
            raise ValueError(f"{strategy}资金曲线为空，请检查数据")
        s = s.rename(columns={'涨跌幅': f'{strategy}'})
        strategies[strategy] = s[['candle_begin_time', f'{strategy}']]

    # 合并所有策略的数据，使用outer join确保包含所有时间点
    df = reduce(
        lambda left, right: pd.merge(left, right, on='candle_begin_time', how='outer'),
        strategies.values()
    )

    return df.set_index('candle_begin_time')


def process_equity_data(root_path, backtest_name, start_time, end_time):
    """
    处理回测和实盘资金曲线数据，并计算对比涨跌幅和资金曲线。

    参数:
    - root_path: 根路径
    - backtest_name: 回测结果文件夹名称
    - start_time: 开始时间（datetime 或字符串）
    - end_time: 结束时间（datetime 或字符串）

    返回:
    - df: 包含回测和实盘资金曲线的 DataFrame
    """
    # 读取回测资金曲线
    backtest_equity = pd.read_csv(
        os.path.join(root_path, f'data/回测结果/{backtest_name}/资金曲线.csv'),
        encoding='utf-8-sig',
        parse_dates=['candle_begin_time']
    )
    # 过滤时间范围
    backtest_equity = backtest_equity[
        (backtest_equity['candle_begin_time'] >= start_time) &
        (backtest_equity['candle_begin_time'] <= end_time)
        ]

    if backtest_equity.empty:
        raise ValueError("回测资金曲线为空，请检查 'start_time' 和 'end_time' 的设置")

    # 计算净值
    backtest_equity['净值'] = backtest_equity['净值'] / backtest_equity['净值'].iloc[0]
    # 重命名列
    backtest_equity = backtest_equity.rename(
        columns={'涨跌幅': '回测涨跌幅', '净值': '回测净值', 'candle_begin_time': 'time'}
    )

    # 读取实盘资金曲线
    trading_equity = pd.read_csv(
        os.path.join(root_path, f'data/回测结果/{backtest_name}/实盘结果/账户信息/equity.csv'),
        encoding='gbk',
        parse_dates=['time']
    )

    # 调整时间偏移
    utc_offset = int(time.localtime().tm_gmtoff / 60 / 60) + 1
    trading_equity['time'] = trading_equity['time'] - pd.Timedelta(f'{utc_offset}H')
    # 格式化时间
    trading_equity['time'] = trading_equity['time'].map(lambda x: x.strftime('%Y-%m-%d %H:00:00'))
    trading_equity['time'] = pd.to_datetime(trading_equity['time'])
    # 过滤时间范围
    trading_equity = trading_equity[
        (trading_equity['time'] >= start_time) &
        (trading_equity['time'] <= end_time)
        ]

    if trading_equity.empty:
        raise ValueError("实盘资金曲线为空，请检查 'start_time' 和 'end_time' 的设置")

    # 计算实盘净值
    trading_equity['实盘净值'] = trading_equity['账户总净值'] / trading_equity['账户总净值'].iloc[0]
    # 计算实盘涨跌幅
    trading_equity['实盘涨跌幅'] = trading_equity['实盘净值'].pct_change()
    # 合并回测和实盘数据
    df = pd.merge(trading_equity, backtest_equity, on='time', how='inner')
    if df.empty:
        raise ValueError("回测和实盘曲线时间无法对齐，请检查数据")

    # 计算对比涨跌幅
    df['对比涨跌幅'] = (df['实盘涨跌幅'] - df['回测涨跌幅']) / 2
    # 计算对比资金曲线
    df['对比资金曲线'] = (df['对比涨跌幅'] + 1).cumprod()

    return df


def process_coin_selection_data(root_path, backtest_name, start_time, end_time):
    """
    处理回测和实盘选币数据，并计算选币的交集、并集、相似度等指标。

    参数:
    - root_path: 根路径
    - backtest_name: 回测结果文件夹名称
    - trading_name: 实盘资金曲线文件夹名称
    - hour_offset: 时间偏移量

    返回:
    - merged: 包含回测和实盘选币数据的 DataFrame
    """
    # 读取回测选币数据
    backtest_coins = pd.read_pickle(os.path.join(root_path, f'data/回测结果/{backtest_name}/final_select_results.pkl'))
    # 过滤时间范围
    backtest_coins = backtest_coins[
        (backtest_coins['candle_begin_time'] >= start_time) &
        (backtest_coins['candle_begin_time'] <= end_time)
        ]
    if backtest_coins.empty:
        raise ValueError("回测选币数据为空，请检查 'start_time' 和 'end_time' 的设置")

    # 目的是和实盘symbol对齐，实盘的symbol没有连字符，比如回测symbol 'BTC-USDT'，实盘对应的symbol为 'BTCUSDT'
    backtest_coins['symbol'] = backtest_coins['symbol'].astype(str)
    backtest_coins['symbol'] = backtest_coins['symbol'].apply(lambda x: x.replace('-', ''))

    # 读取实盘选币数据
    trading_coins = pd.DataFrame()
    path = os.path.join(root_path, f'data/回测结果/{backtest_name}/实盘结果/select_coin')
    pkl_files = [f for f in os.listdir(path) if f.endswith('.pkl')]
    if len(pkl_files) == 0:
        raise ValueError("对应文件夹下没有相关性的实盘选币数据，请检查")
    for pkl_file in pkl_files:
        pkl_file_temp = pd.read_pickle(os.path.join(path, pkl_file))
        if pkl_file_temp.empty:
            raise ValueError(f"{pkl_file} 数据为空，请检查数据")
        trading_coins = pd.concat([trading_coins, pkl_file_temp], ignore_index=True)

    # 调整实盘选币数据的时间
    trading_coins['candle_begin_time'] = trading_coins['candle_begin_time'].map(
        lambda x: x.strftime('%Y-%m-%d %H:00:00'))
    trading_coins['candle_begin_time'] = pd.to_datetime(trading_coins['candle_begin_time'])

    # 过滤时间范围
    trading_coins = trading_coins[
        (trading_coins['candle_begin_time'] >= start_time) &
        (trading_coins['candle_begin_time'] <= end_time)
        ]
    if trading_coins.empty:
        raise ValueError("实盘选币数据为空，请检查 'start_time' 和 'end_time' 的设置")

    # 按时间分组并生成选币集合
    backtest_coins['symbol_type'] = backtest_coins['is_spot'].map({1: 'spot', 0: 'swap'})
    backtest_coins['方向'] = backtest_coins['方向'].astype(int)
    backtest_coins['coins_name'] = (backtest_coins['symbol'] + '(' + backtest_coins['symbol_type'] + ','
                                    + backtest_coins['方向'].astype(str) + ')')

    trading_coins['symbol_type'] = trading_coins['symbol_type'].astype(str)
    trading_coins['coins_name'] = trading_coins['symbol'] + '(' + trading_coins['symbol_type'] + ',' + trading_coins[
        '方向'].astype(str) + ')'

    backtest_coins = backtest_coins.groupby('candle_begin_time').apply(lambda x: set(x['coins_name']))
    backtest_coins = backtest_coins.to_frame().reset_index().rename(columns={0: f'回测-{backtest_name}'})

    trading_coins = trading_coins.groupby('candle_begin_time').apply(lambda x: set(x['coins_name']))
    trading_coins = trading_coins.to_frame().reset_index().rename(columns={0: f'实盘-{backtest_name}'})

    # 合并回测和实盘选币数据
    merged = pd.merge(backtest_coins, trading_coins, on='candle_begin_time', how='inner')
    if merged.empty:
        raise ValueError("回测和实盘选币时间无法对齐，请检查数据")

    # 计算指标
    merged['共有选币'] = merged.apply(lambda x: x[f'回测-{backtest_name}'] & x[f'实盘-{backtest_name}'], axis=1)
    # 计算回测选币独有（在回测中但不在交集中）
    merged['回测独有选币'] = merged.apply(lambda x: x[f'回测-{backtest_name}'] - x['共有选币'], axis=1)
    # 计算实盘选币独有（在实盘中但不在交集中）
    merged['实盘独有选币'] = merged.apply(lambda x: x[f'实盘-{backtest_name}'] - x['共有选币'], axis=1)
    merged[f'回测-{backtest_name}选币数量'] = merged[f'回测-{backtest_name}'].str.len()
    merged[f'实盘-{backtest_name}选币数量'] = merged[f'实盘-{backtest_name}'].str.len()
    merged['重复选币数量'] = merged['共有选币'].str.len()
    merged[f'相似度_基于回测-{backtest_name}'] = merged['共有选币'].str.len() / merged[f'回测-{backtest_name}选币数量']
    merged[f'相似度_基于实盘-{backtest_name}'] = merged['共有选币'].str.len() / merged[f'实盘-{backtest_name}选币数量']
    merged['相似度'] = (merged[f'相似度_基于回测-{backtest_name}'] + merged[f'相似度_基于实盘-{backtest_name}']) / 2

    return merged
