"""
Quant Unified 量化交易系统
基础函数.py

功能：
    提供数据清洗、最小下单量加载、交易对过滤等通用函数。
"""
import warnings
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

# 稳定币信息，不参与交易的币种
稳定币列表 = ['BKRW', 'USDC', 'USDP', 'TUSD', 'BUSD', 'FDUSD', 'DAI', 'EUR', 'GBP', 'USBP', 'SUSD', 'PAXG', 'AEUR']

# ====================================================================================================
# ** 策略相关函数 **
# ====================================================================================================
def 删除数据不足币种(symbol_candle_data) -> Dict[str, pd.DataFrame]:
    """
    删除数据长度不足的币种信息

    :param symbol_candle_data:
    :return
    """
    # ===删除成交量为0的线数据、k线数不足的币种
    symbol_list = list(symbol_candle_data.keys())
    for symbol in symbol_list:
        # 删除空的数据
        if symbol_candle_data[symbol] is None or symbol_candle_data[symbol].empty:
            del symbol_candle_data[symbol]
            continue
        # 删除该币种成交量=0的k线
        # symbol_candle_data[symbol] = symbol_candle_data[symbol][symbol_candle_data[symbol]['volume'] > 0]

    return symbol_candle_data


def 忽略错误(anything):
    return anything


def 读取最小下单量(file_path: Path) -> (int, Dict[str, int]):
    # 读取min_qty文件并转为dict格式
    min_qty_df = pd.read_csv(file_path, encoding='utf-8-sig')
    min_qty_df['最小下单量'] = -np.log10(min_qty_df['最小下单量']).round().astype(int)
    default_min_qty = min_qty_df['最小下单量'].max()
    min_qty_df.set_index('币种', inplace=True)
    min_qty_dict = min_qty_df['最小下单量'].to_dict()

    return default_min_qty, min_qty_dict


def 是否为交易币种(symbol, black_list=()) -> bool:
    """
    过滤掉不能用于交易的币种，比如稳定币、非USDT交易对，以及一些杠杆币
    :param symbol: 交易对
    :param black_list: 黑名单
    :return: 是否可以进入交易，True可以参与选币，False不参与
    """
    # 如果symbol为空
    # 或者是.开头的隐藏文件
    # 或者不是USDT结尾的币种
    # 或者在黑名单里
    if not symbol or symbol.startswith('.') or not symbol.endswith('USDT') or symbol in black_list:
        return False

    # 筛选杠杆币
    base_symbol = symbol.upper().replace('-USDT', 'USDT')[:-4]
    if base_symbol.endswith(('UP', 'DOWN', 'BEAR', 'BULL')) and base_symbol != 'JUP' or base_symbol in 稳定币列表:
        return False
    else:
        return True

# Alias
del_insufficient_data = 删除数据不足币种
load_min_qty = 读取最小下单量
is_trade_symbol = 是否为交易币种
stable_symbol = 稳定币列表
