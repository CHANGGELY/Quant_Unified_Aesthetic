"""
Quant Unified 量化交易系统
02_计算因子.py

功能：
    并行计算选币策略配置的所有因子。
"""
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
from tqdm import tqdm

from ..核心.模型.配置 import 回测配置
from ..核心.工具.因子中心 import 因子中心
from ..核心.工具.路径 import 获取文件路径

# pandas相关的显示设置
pd.set_option('expand_frame_repr', False)
pd.set_option('display.unicode.ambiguous_as_wide', True)
pd.set_option('display.unicode.east_asian_width', True)


def 转换日线数据(df, date_col='candle_begin_time'):
    """
    将K线数据转化为日线数据
    """
    # 设置日期列为索引，以便进行重采样
    df.set_index(date_col, inplace=True)

    # 定义K线数据聚合规则
    agg_dict = {
        'symbol': 'first',
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'quote_volume': 'sum',
        'trade_num': 'sum',
        'taker_buy_base_asset_volume': 'sum',
        'taker_buy_quote_asset_volume': 'sum',
        'funding_fee': 'sum',
        'first_candle_time': 'first',
        '是否交易': 'last',
        'is_spot': 'first',
    }

    # 按日重采样并应用聚合规则
    df = df.resample('1D').agg(agg_dict)
    df.reset_index(inplace=True)
    return df


def 单币种计算因子(conf: 回测配置, candle_df) -> pd.DataFrame:
    """
    针对单一币种的K线数据，计算所有因子的值
    """
    # 如果是日线策略，需要转化为日线数据
    if conf.is_day_period:
        candle_df = 转换日线数据(candle_df)

    # 去除无效数据并计算因子
    candle_df.dropna(subset=['symbol'], inplace=True)
    candle_df.reset_index(drop=True, inplace=True)

    factor_series_dict = {}  # 存储因子计算结果的字典

    # 遍历因子配置，逐个计算
    for factor_name, param_list in conf.factor_params_dict.items():
        try:
            factor = 因子中心.获取因子(factor_name)  # 获取因子对象
        except ValueError as e:
            print(f"⚠️ 警告: 无法加载因子 {factor_name}: {e}")
            continue

        # 创建一份独立的K线数据供因子计算使用
        legacy_candle_df = candle_df.copy()
        for param in param_list:
            factor_col_name = f'{factor_name}_{str(param)}'
            # 计算因子信号并添加到结果字典
            try:
                legacy_candle_df = factor.signal(legacy_candle_df, param, factor_col_name)
                factor_series_dict[factor_col_name] = legacy_candle_df[factor_col_name]
            except Exception as e:
                # print(f"计算因子 {factor_col_name} 失败: {e}")
                pass

    # 整合K线和因子数据
    kline_with_factor_dict = {
        'candle_begin_time': candle_df['candle_begin_time'],
        'symbol': candle_df['symbol'],
        'is_spot': candle_df['is_spot'],
        'close': candle_df['close'],
        'next_close': candle_df['close'].shift(-1),
        **factor_series_dict,
        '是否交易': candle_df['是否交易'],
    }

    # 转换为DataFrame并按时间排序
    kline_with_factor_df = pd.DataFrame(kline_with_factor_dict)
    kline_with_factor_df.sort_values(by='candle_begin_time', inplace=True)

    # 根据配置条件过滤数据
    first_candle_time = candle_df.iloc[0]['first_candle_time'] + pd.to_timedelta(f'{conf.min_kline_num}h')
    kline_with_factor_df = kline_with_factor_df[kline_with_factor_df['candle_begin_time'] >= first_candle_time]

    # 去掉最后一个周期数据
    if kline_with_factor_df['candle_begin_time'].max() < pd.to_datetime(conf.end_date):
        _temp_time = kline_with_factor_df['candle_begin_time'] + pd.Timedelta(conf.hold_period)
        
        # 安全处理: 检查 index 是否在范围内
        valid_indices = _temp_time.index[(_temp_time.index >= kline_with_factor_df.index.min()) & 
                                         (_temp_time.index <= kline_with_factor_df.index.max())]
        
        if not valid_indices.empty:
             # 这里逻辑有点绕，主要是为了防止最后时刻没有 next_close
            _del_time = kline_with_factor_df.loc[valid_indices][
                kline_with_factor_df.loc[valid_indices, 'next_close'].isna()
            ]['candle_begin_time']
            
            if not _del_time.empty:
                kline_with_factor_df = kline_with_factor_df[
                    kline_with_factor_df['candle_begin_time'] <= _del_time.min() - pd.Timedelta(conf.hold_period)]

    # 只保留配置时间范围内的数据
    kline_with_factor_df = kline_with_factor_df[
        (kline_with_factor_df['candle_begin_time'] >= pd.to_datetime(conf.start_date)) &
        (kline_with_factor_df['candle_begin_time'] < pd.to_datetime(conf.end_date))]

    return kline_with_factor_df  # 返回计算后的因子数据


def 计算因子(conf: 回测配置):
    """
    计算因子主函数
    """
    print('🌀 开始计算因子...')
    s_time = time.time()
    
    max_workers = getattr(conf, 'max_workers', 4)

    # ====================================================================================================
    # 1. 读取所有币种的K线数据
    # ====================================================================================================
    data_path = 获取文件路径('data', 'cache', 'all_candle_df_list.pkl')
    try:
        candle_df_list = pd.read_pickle(data_path)
    except FileNotFoundError:
        print(f'❌ 错误：未找到数据文件 {data_path}。请先运行 `01_准备数据.py`。')
        return

    # ====================================================================================================
    # 2. 并行计算因子
    # ====================================================================================================
    all_factor_df_list = []
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(单币种计算因子, conf, candle_df) for candle_df in candle_df_list]
        for future in tqdm(as_completed(futures), total=len(candle_df_list), desc='🧮 计算因子'):
            try:
                # 计算因子
                factor_df = future.result()
                if factor_df is not None and not factor_df.empty:
                    all_factor_df_list.append(factor_df)
            except Exception as e:
                print(f'计算因子遇到问题: {e}')
                # raise e

    # ====================================================================================================
    # 3. 合并所有因子数据并存储
    # ====================================================================================================
    if not all_factor_df_list:
        print('❌ 错误：因子数据列表为空，无法进行合并。')
        return

    all_factors_df = pd.concat(all_factor_df_list, ignore_index=True)
    all_factors_df['symbol'] = pd.Categorical(all_factors_df['symbol'])

    pkl_path = 获取文件路径('data', 'cache', 'all_factors_df.pkl', as_path_type=True)

    all_factors_df = all_factors_df.sort_values(by=['candle_begin_time', 'symbol']).reset_index(drop=True)
    all_factors_df.to_pickle(pkl_path)

    # 针对每一个因子进行存储 (用于选币分析等)
    # 注意：这里会产生很多小文件
    for factor_col_name in conf.factor_col_name_list:
        if factor_col_name not in all_factors_df.columns:
            continue
        all_factors_df[factor_col_name].to_pickle(pkl_path.with_name(f'factor_{factor_col_name}.pkl'))

    print(f'✅ 因子计算完成，耗时：{time.time() - s_time:.2f}秒')
    print()

# Alias
calc_factors = 计算因子