"""
Quant Unified 量化交易系统
01_准备数据.py

功能：
    读取、清洗和整理加密货币的K线数据，为回测和行情分析提供预处理的数据文件。
"""
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

from ..核心.模型.配置 import 回测配置
from ..核心.工具.基础函数 import 是否为交易币种
from ..核心.工具.路径 import 获取文件路径

# pandas相关的显示设置
pd.set_option('expand_frame_repr', False)
pd.set_option('display.unicode.ambiguous_as_wide', True)
pd.set_option('display.unicode.east_asian_width', True)
pd.set_option('display.width', 100)


def 预处理K线(filename, is_spot) -> pd.DataFrame:
    """
    预处理单个交易对的K线数据文件，确保数据的完整性和一致性。
    """
    # 读取CSV文件，指定编码并解析时间列，跳过文件中的第一行（表头）
    df = pd.read_csv(filename, encoding='gbk', parse_dates=['candle_begin_time'], skiprows=1)
    # 删除重复的时间点记录，仅保留最后一次记录
    df.drop_duplicates(subset=['candle_begin_time'], inplace=True, keep='last')

    candle_data_dict = {}
    is_swap = 'fundingRate' in df.columns

    # 获取K线数据中最早和最晚的时间
    first_candle_time = df['candle_begin_time'].min()
    last_candle_time = df['candle_begin_time'].max()

    # 构建1小时的时间范围，确保数据的连续性
    hourly_range = pd.DataFrame(pd.date_range(start=first_candle_time, end=last_candle_time, freq='1h'))
    hourly_range.rename(columns={0: 'candle_begin_time'}, inplace=True)

    # 将原始数据与连续时间序列合并
    df = pd.merge(left=hourly_range, right=df, on='candle_begin_time', how='left', sort=True, indicator=True)
    df.sort_values(by='candle_begin_time', inplace=True)
    df.drop_duplicates(subset=['candle_begin_time'], inplace=True, keep='last')

    # 填充缺失值
    df['close'] = df['close'].ffill()
    df['open'] = df['open'].fillna(df['close'])

    candle_data_dict['candle_begin_time'] = df['candle_begin_time']
    candle_data_dict['symbol'] = pd.Categorical(df['symbol'].ffill())

    candle_data_dict['open'] = df['open']
    candle_data_dict['high'] = df['high'].fillna(df['close'])
    candle_data_dict['close'] = df['close']
    candle_data_dict['low'] = df['low'].fillna(df['close'])

    candle_data_dict['volume'] = df['volume'].fillna(0)
    candle_data_dict['quote_volume'] = df['quote_volume'].fillna(0)
    candle_data_dict['trade_num'] = df['trade_num'].fillna(0)
    candle_data_dict['taker_buy_base_asset_volume'] = df['taker_buy_base_asset_volume'].fillna(0)
    candle_data_dict['taker_buy_quote_asset_volume'] = df['taker_buy_quote_asset_volume'].fillna(0)
    candle_data_dict['funding_fee'] = df['fundingRate'].fillna(0) if is_swap else 0
    candle_data_dict['avg_price_1m'] = df['avg_price_1m'].fillna(df['open'])
    
    if 'avg_price_5m' in df.columns:
        candle_data_dict['avg_price_5m'] = df['avg_price_5m'].fillna(df['open'])

    candle_data_dict['是否交易'] = np.where(df['volume'] > 0, 1, 0).astype(np.int8)

    candle_data_dict['first_candle_time'] = pd.Series([first_candle_time] * len(df))
    candle_data_dict['last_candle_time'] = pd.Series([last_candle_time] * len(df))
    candle_data_dict['is_spot'] = int(is_spot)

    return pd.DataFrame(candle_data_dict)


def 生成行情透视表(market_dict, start_date):
    """
    生成行情数据的pivot表
    """
    cols = ['candle_begin_time', 'symbol', 'open', 'close', 'funding_fee', 'avg_price_1m']

    print('- [透视表] 将行情数据合并转换为DataFrame格式...')
    df_list = []
    for df in market_dict.values():
        df2 = df.loc[df['candle_begin_time'] >= pd.to_datetime(start_date), cols].dropna(subset='symbol')
        df_list.append(df2)
    
    if not df_list:
        return {}
        
    df_all_market = pd.concat(df_list, ignore_index=True)
    df_all_market['symbol'] = pd.Categorical(df_all_market['symbol'])

    print('- [透视表] 将开盘价数据转换为pivot表...')
    df_open = df_all_market.pivot(values='open', index='candle_begin_time', columns='symbol')
    print('- [透视表] 将收盘价数据转换为pivot表...')
    df_close = df_all_market.pivot(values='close', index='candle_begin_time', columns='symbol')
    print('- [透视表] 将1分钟的均价数据转换为pivot表...')
    df_vwap1m = df_all_market.pivot(values='avg_price_1m', index='candle_begin_time', columns='symbol')
    print('- [透视表] 将资金费率数据转换为pivot表...')
    df_rate = df_all_market.pivot(values='funding_fee', index='candle_begin_time', columns='symbol')
    print('- [透视表] 将缺失值填充为0...')
    df_rate.fillna(value=0, inplace=True)

    return {
        'open': df_open,
        'close': df_close,
        'funding_rate': df_rate,
        'vwap1m': df_vwap1m
    }


def 准备数据(conf: 回测配置):
    """
    数据准备主函数
    """
    print('🌀 数据准备...')
    s_time = time.time()
    
    # 从配置对象获取路径参数 (需要在外部注入)
    spot_path = getattr(conf, 'spot_path', None)
    swap_path = getattr(conf, 'swap_path', None)
    max_workers = getattr(conf, 'max_workers', 4)
    
    if spot_path is None or swap_path is None:
        raise ValueError("回测配置中缺少 'spot_path' 或 'swap_path'。")

    # ====================================================================================================
    # 1. 获取交易对列表
    # ====================================================================================================
    print('💿 加载现货和合约数据...')
    spot_candle_data_dict = {}
    swap_candle_data_dict = {}

    # 处理spot数据
    spot_symbol_list = []
    if Path(spot_path).exists():
        for file_path in Path(spot_path).rglob('*-USDT.csv'):
            if 是否为交易币种(file_path.stem):
                spot_symbol_list.append(file_path.stem)
    print(f'📂 读取到的spot交易对数量：{len(spot_symbol_list)}')

    # 处理swap数据
    swap_symbol_list = []
    if Path(swap_path).exists():
        for file_path in Path(swap_path).rglob('*-USDT.csv'):
            if 是否为交易币种(file_path.stem):
                swap_symbol_list.append(file_path.stem)
    print(f'📂 读取到的swap交易对数量：{len(swap_symbol_list)}')

    # ====================================================================================================
    # 2. 逐个读取和预处理交易数据
    # ====================================================================================================

    # 处理spot数据
    if not {'spot', 'mix'}.isdisjoint(conf.select_scope_set):
        print('ℹ️ 读取并且预处理spot交易数据...')
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(预处理K线, Path(spot_path) / f'{symbol}.csv', True): symbol for symbol in
                       spot_symbol_list}
            for future in tqdm(as_completed(futures), total=len(spot_symbol_list), desc='💼 处理spot数据'):
                try:
                    data = future.result()
                    symbol = futures[future]
                    spot_candle_data_dict[symbol] = data
                except Exception as e:
                    print(f'❌ 预处理spot交易数据失败，错误信息：{e}')

    # 处理swap数据
    if not {'swap', 'mix'}.isdisjoint(conf.select_scope_set) or not {'swap'}.isdisjoint(conf.order_first_set):
        print('ℹ️ 读取并且预处理swap交易数据...')
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(预处理K线, Path(swap_path) / f'{symbol}.csv', False): symbol for symbol in
                       swap_symbol_list}
            for future in tqdm(as_completed(futures), total=len(swap_symbol_list), desc='💼 处理swap数据'):
                try:
                    data = future.result()
                    symbol = futures[future]
                    swap_candle_data_dict[symbol] = data
                except Exception as e:
                    print(f'❌ 预处理swap交易数据失败，错误信息：{e}')

    candle_data_dict = swap_candle_data_dict or spot_candle_data_dict
    # 保存交易数据
    pd.to_pickle(candle_data_dict, 获取文件路径('data', 'candle_data_dict.pkl'))

    # ====================================================================================================
    # 3. 缓存所有K线数据
    # ====================================================================================================
    all_candle_df_list = []
    for symbol, candle_df in candle_data_dict.items():
        if symbol not in conf.black_list:
            all_candle_df_list.append(candle_df)
    pd.to_pickle(all_candle_df_list, 获取文件路径('data', 'cache', 'all_candle_df_list.pkl'))

    # ====================================================================================================
    # 4. 创建行情pivot表并保存
    # ====================================================================================================
    print('ℹ️ 预处理行情数据...')
    market_pivot_spot = None
    market_pivot_swap = None
    
    if spot_candle_data_dict:
        market_pivot_spot = 生成行情透视表(spot_candle_data_dict, conf.start_date)
    if swap_candle_data_dict:
        market_pivot_swap = 生成行情透视表(swap_candle_data_dict, conf.start_date)

    if not spot_candle_data_dict:
        market_pivot_spot = market_pivot_swap
    if not swap_candle_data_dict:
        market_pivot_swap = market_pivot_spot

    pd.to_pickle(market_pivot_spot, 获取文件路径('data', 'market_pivot_spot.pkl'))
    pd.to_pickle(market_pivot_swap, 获取文件路径('data', 'market_pivot_swap.pkl'))

    print(f'✅ 完成数据预处理，花费时间：{time.time() - s_time:.2f}秒')
    print()

    return all_candle_df_list, market_pivot_swap if swap_candle_data_dict else market_pivot_spot

# Alias
prepare_data = 准备数据