"""
Quant Unified 量化交易系统
kline.py
"""
import os
import time
import traceback
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from glob import glob
from functools import partial

import numpy as np
import pandas as pd
from tqdm import tqdm

# Import config from strategy
from config import data_center_path, special_symbol_dict, download_kline_list, exchange_basic_config, utc_offset, stable_symbol
# Import Async Client
from common_core.exchange.binance_async import AsyncBinanceClient
from core.utils.path_kit import get_folder_path, get_file_path
from data_job.funding_fee import load_funding_fee

# 提取文件名
script_filename = os.path.basename(os.path.abspath(__file__)).split('.')[0]

# 首次初始化需要多少k线数据，根据你策略因子需要调整
init_kline_num = 1500

# 根据持仓周期自动调整获取1小时的k线
interval = '1h'

# 获取交易所对象 (Global Async Client will be initialized in main loop)
cli = None

# ====================================================================================================
# ** 辅助函数区域 **
# ====================================================================================================
def has_spot():
    return 'SPOT' in download_kline_list or 'spot' in download_kline_list

def has_swap():
    return 'SWAP' in download_kline_list or 'swap' in download_kline_list

def add_swap_tag(spot_df, swap_df):
    spot_df['tag'] = 'NoSwap'
    if swap_df is None or swap_df.empty:
        return spot_df

    cond1 = spot_df['candle_begin_time'] > swap_df.iloc[0]['candle_begin_time']
    cond2 = spot_df['candle_begin_time'] <= swap_df.iloc[-1]['candle_begin_time']
    spot_df.loc[cond1 & cond2, 'tag'] = 'HasSwap'
    return spot_df

def export_to_csv(df, symbol, symbol_type):
    """
    Export DataFrame to CSV (Sync function, to be run in executor)
    """
    # ===在data目录下创建当前脚本存放数据的目录
    save_path = get_folder_path(data_center_path, script_filename, symbol_type)

    # =构建存储文件的路径
    _file_path = os.path.join(save_path, f'{symbol}.csv')

    # =判断文件是否存在
    if_file_exists = os.path.exists(_file_path)
    # =保存数据
    # 路径存在，数据直接追加
    if if_file_exists:
        df[-10:].to_csv(_file_path, encoding='gbk', index=False, header=False, mode='a')
        # No need to sleep in async context, but kept for safety if file system is slow
        # time.sleep(0.05) 
    else:
        df.to_csv(_file_path, encoding='gbk', index=False)
        # time.sleep(0.3)

async def fetch_and_save_symbol(symbol, symbol_type, run_time, swap_funding_df=None):
    """
    Async fetch and save for a single symbol
    """
    save_file_path = get_file_path(data_center_path, script_filename, symbol_type, f'{symbol}.csv')

    # Determine limit
    kline_limit = 99 if os.path.exists(save_file_path) else init_kline_num

    # Async Fetch
    df = await cli.get_candle_df(symbol, run_time, kline_limit, interval=interval, symbol_type=symbol_type)

    if df is None or df.empty:
        return None

    # Merge Funding Fee (CPU bound, fast enough)
    if symbol_type == 'spot':
        df['fundingRate'] = np.nan
    else:
        if swap_funding_df is None:
            df['fundingRate'] = np.nan
        else:
            df = pd.merge(
                df, swap_funding_df[['fundingTime', 'fundingRate']], left_on=['candle_begin_time'],
                right_on=['fundingTime'], how='left')
            if 'fundingTime' in df.columns:
                del df['fundingTime']
    
    return df

async def process_pair_async(spot_symbol, swap_symbol, run_time, last_funding_df):
    """
    Process a pair of spot/swap symbols
    """
    tasks = []
    
    # Prepare Swap Task
    swap_funding_df = None
    if swap_symbol and last_funding_df is not None:
         swap_funding_df = last_funding_df[last_funding_df['symbol'] == swap_symbol].copy()

    if swap_symbol:
        tasks.append(fetch_and_save_symbol(swap_symbol, 'swap', run_time, swap_funding_df))
    else:
        tasks.append(asyncio.sleep(0, result=None)) # Placeholder

    if spot_symbol:
        tasks.append(fetch_and_save_symbol(spot_symbol, 'spot', run_time, None))
    else:
        tasks.append(asyncio.sleep(0, result=None)) # Placeholder

    # Await both
    results = await asyncio.gather(*tasks)
    swap_df, spot_df = results[0], results[1]

    # Save to CSV (Run in ThreadPool to avoid blocking event loop)
    loop = asyncio.get_running_loop()
    
    save_tasks = []
    if swap_df is not None:
        swap_df['tag'] = 'NoSwap'
        save_tasks.append(loop.run_in_executor(None, export_to_csv, swap_df, swap_symbol, 'swap'))

    if spot_df is not None:
        if swap_df is not None:
             spot_df = add_swap_tag(spot_df, swap_df)
        save_tasks.append(loop.run_in_executor(None, export_to_csv, spot_df, spot_symbol, 'spot'))
    
    if save_tasks:
        await asyncio.gather(*save_tasks)

def upgrade_spot_has_swap(spot_symbol, swap_symbol):
    # 先更新swap数据
    swap_df = None
    if swap_symbol:
        swap_filepath = get_file_path(data_center_path, script_filename, 'swap', swap_symbol)
        if os.path.exists(swap_filepath):
            swap_df = pd.read_csv(swap_filepath, encoding='gbk', parse_dates=['candle_begin_time'])
            swap_df['tag'] = 'NoSwap'
            export_to_csv(swap_df, swap_symbol, 'swap')

    if spot_symbol:
        spot_filepath = get_file_path(data_center_path, script_filename, 'spot', spot_symbol)
        if os.path.exists(spot_filepath):
            spot_df = pd.read_csv(
                spot_filepath, encoding='gbk',
                parse_dates=['candle_begin_time']
            ) if spot_symbol else None
            spot_df = add_swap_tag(spot_df, swap_df)
            export_to_csv(spot_df, spot_symbol, 'spot')
    print(f'✅{spot_symbol} / {swap_symbol} updated')


# ====================================================================================================
# ** 数据中心功能函数 **
# ====================================================================================================
async def async_download(run_time):
    global cli
    cli = AsyncBinanceClient(
        exchange_config=exchange_basic_config,
        utc_offset=utc_offset,
        stable_symbol=stable_symbol
    )
    
    try:
        print(f'执行{script_filename}脚本 download (Async) 开始')
        _time = datetime.now()

        print(f'(1/4) 获取交易对...')
        if has_swap():
            swap_market_info = await cli.get_market_info(symbol_type='swap', require_update=True)
            swap_symbol_list = swap_market_info.get('symbol_list', [])
        else:
            swap_symbol_list = []
        
        if has_spot():
            spot_market_info = await cli.get_market_info(symbol_type='spot', require_update=True)
            spot_symbol_list = spot_market_info.get('symbol_list', [])
        else:
            spot_symbol_list = []

        print(f'(2/4) 读取历史资金费率...')
        last_funding_df = load_funding_fee()

        print(f'(3/4) 合并计算交易对...')
        # Same logic as before
        same_symbols = set(spot_symbol_list) & set(swap_symbol_list)
        all_symbols = set(spot_symbol_list) | set(swap_symbol_list)

        if has_spot() and has_swap():
            special_symbol_with_usdt_dict = {
                f'{_spot}USDT'.upper(): f'{_special_swap}USDT'.upper() for _spot, _special_swap in
                special_symbol_dict.items()
            }
        else:
            special_symbol_with_usdt_dict = {}

        symbol_pair_list1 = [(_spot, _spot) for _spot in same_symbols]
        symbol_pair_list2 = [(_spot, _swap) for _spot, _swap in special_symbol_with_usdt_dict.items()]

        symbol_pair_list3 = []
        for _spot in spot_symbol_list:
            _special_swap = f'1000{_spot}'
            if _special_swap in swap_symbol_list:
                symbol_pair_list3.append((_spot, _special_swap))
                special_symbol_with_usdt_dict[_spot] = _special_swap

        symbol_pair_list4 = [
            (None, _symbol) if _symbol in swap_symbol_list else (_symbol, special_symbol_with_usdt_dict.get(_symbol, None))
            for _symbol in all_symbols if
            _symbol not in [*same_symbols, *special_symbol_with_usdt_dict.keys(), *special_symbol_with_usdt_dict.values()]
        ]
        symbol_pair_list = symbol_pair_list1 + symbol_pair_list2 + symbol_pair_list3 + symbol_pair_list4

        # Check has_swap cache
        has_swap_check = get_file_path(data_center_path, 'kline-has-swap.txt')
        if not os.path.exists(has_swap_check):
            print('⚠️开始更新数据缓存文件，添加HasSwap的tag...')
            # This is slow, maybe optimize later? For now keep sync or run in thread
            # Since it's one-off, just run it.
            for spot_symbol, swap_symbol in symbol_pair_list:
                upgrade_spot_has_swap(spot_symbol, swap_symbol)
            with open(has_swap_check, 'w') as f:
                f.write('HasSwap')

        print(f'(4/4) 开始更新数据 (Async Parallel)...')
        
        # Batch processing to control concurrency if needed, but aiohttp can handle many.
        # Let's process all at once or in chunks of 50.
        chunk_size = 50
        total_pairs = len(symbol_pair_list)
        
        for i in range(0, total_pairs, chunk_size):
            chunk = symbol_pair_list[i:i + chunk_size]
            print(f'Processing chunk {i//chunk_size + 1}/{(total_pairs + chunk_size - 1)//chunk_size}...')
            tasks = [process_pair_async(spot, swap, run_time, last_funding_df) for spot, swap in chunk]
            await asyncio.gather(*tasks)

        # Generate timestamp file
        with open(get_file_path(data_center_path, script_filename, 'kline-download-time.txt'), 'w') as f:
            f.write(run_time.strftime('%Y-%m-%d %H:%M:%S'))

        print(f'✅执行{script_filename}脚本 download 完成。({datetime.now() - _time})')
        
    finally:
        await cli.close()

def download(run_time):
    asyncio.run(async_download(run_time))

def clear_duplicates(file_path):
    # 文件存在，去重之后重新保存
    if os.path.exists(file_path):
        df = pd.read_csv(file_path, encoding='gbk', parse_dates=['candle_begin_time'])  # 读取本地数据
        df.drop_duplicates(subset=['candle_begin_time'], keep='last', inplace=True)  # 去重保留最新的数据
        df.sort_values('candle_begin_time', inplace=True)  # 通过candle_begin_time排序
        df = df[-init_kline_num:]  # 保留最近2400根k线，防止数据堆积过多(2400根，大概100天数据)
        df.to_csv(file_path, encoding='gbk', index=False)  # 保存文件


def clean_data():
    """
    根据获取数据的情况，自行编写清理冗余数据函数
    """
    print(f'ℹ️执行{script_filename}脚本 clear_duplicates 开始')
    _time = datetime.now()
    # 遍历合约和现货目录
    for symbol_type in ['swap', 'spot']:
        # 获取目录路径
        save_path = os.path.join(data_center_path, script_filename, symbol_type)
        # 获取.csv结尾的文件目录
        file_list = glob(get_file_path(save_path, '*.csv'))
        # 遍历文件进行操作
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(clear_duplicates, _file) for _file in file_list]

            for future in tqdm(as_completed(futures), total=len(futures), desc='清理冗余数据'):
                try:
                    future.result()
                except Exception as e:
                    print(f"❌An error occurred: {e}")
                    print(traceback.format_exc())

    print(f'✅执行{script_filename}脚本 clear_duplicates 完成 {datetime.now() - _time}')


if __name__ == '__main__':
    download(datetime.now().replace(minute=0))
