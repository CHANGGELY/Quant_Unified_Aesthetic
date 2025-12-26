"""
Quant Unified 量化交易系统
[币安异步交易客户端]
功能：基于 AsyncIO 实现高并发行情获取与交易指令发送，大幅提升数据下载和实盘响应速度。
"""
import asyncio
import math
import time
import traceback
import ccxt.async_support as ccxt  # 异步 CCXT
import pandas as pd
import numpy as np

from common_core.exchange.base_client import BinanceClient
from common_core.utils.async_commons import async_retry_wrapper

class AsyncBinanceClient(BinanceClient):
    def __init__(self, **config):
        super().__init__(**config)
        # 使用异步版本覆盖 self.exchange
        default_exchange_config = {
            'timeout': 30000,
            'rateLimit': 30,
            'enableRateLimit': False,
            'options': {'adjustForTimeDifference': True, 'recvWindow': 10000},
        }
        self.exchange = ccxt.binance(config.get('exchange_config', default_exchange_config))
    
    async def close(self):
        await self.exchange.close()

    async def _fetch_swap_exchange_info_list(self) -> list:
        exchange_info = await async_retry_wrapper(self.exchange.fapipublic_get_exchangeinfo, func_name='获取BN合约币种规则数据')
        return exchange_info['symbols']

    async def _fetch_spot_exchange_info_list(self) -> list:
        exchange_info = await async_retry_wrapper(self.exchange.public_get_exchangeinfo, func_name='获取BN现货币种规则数据')
        return exchange_info['symbols']

    async def fetch_market_info(self, symbol_type='swap', quote_symbol='USDT'):
        print(f'🔄(Async) 更新{symbol_type}市场数据...')
        if symbol_type == 'swap':
            exchange_info_list = await self._fetch_swap_exchange_info_list()
        else:
            exchange_info_list = await self._fetch_spot_exchange_info_list()
        
        # 复用基类逻辑？
        # 逻辑是处理列表。我们可以复制或提取它。
        # 为了速度，我将在这里复制处理逻辑。
        
        symbol_list = []
        full_symbol_list = []
        min_qty = {}
        price_precision = {}
        min_notional = {}

        for info in exchange_info_list:
            symbol = info['symbol']
            if info['quoteAsset'] != quote_symbol or info['status'] != 'TRADING':
                continue
            full_symbol_list.append(symbol)

            if (symbol_type == 'swap' and info['contractType'] != 'PERPETUAL') or info['baseAsset'] in self.stable_symbol:
                pass
            else:
                symbol_list.append(symbol)

            for _filter in info['filters']:
                if _filter['filterType'] == 'PRICE_FILTER':
                    price_precision[symbol] = int(math.log(float(_filter['tickSize']), 0.1))
                elif _filter['filterType'] == 'LOT_SIZE':
                    min_qty[symbol] = int(math.log(float(_filter['minQty']), 0.1))
                elif _filter['filterType'] == 'MIN_NOTIONAL' and symbol_type == 'swap':
                    min_notional[symbol] = float(_filter['notional'])
                elif _filter['filterType'] == 'NOTIONAL' and symbol_type == 'spot':
                    min_notional[symbol] = float(_filter['minNotional'])

        self.market_info[symbol_type] = {
            'symbol_list': symbol_list,
            'full_symbol_list': full_symbol_list,
            'min_qty': min_qty,
            'price_precision': price_precision,
            'min_notional': min_notional,
            'last_update': int(time.time())
        }
        return self.market_info[symbol_type]

    async def get_market_info(self, symbol_type, expire_seconds: int = 3600 * 12, require_update: bool = False, quote_symbol='USDT'):
        if require_update:
            last_update = 0
        else:
            last_update = self.market_info.get(symbol_type, {}).get('last_update', 0)
        
        if last_update + expire_seconds < int(time.time()):
            await self.fetch_market_info(symbol_type, quote_symbol)
        
        return self.market_info[symbol_type]

    async def get_candle_df(self, symbol, run_time, limit=1500, interval='1h', symbol_type='swap') -> pd.DataFrame:
        _limit = limit
        if limit > 1000:
            if symbol_type == 'spot':
                _limit = 1000
            else:
                _limit = 499
        
        start_time_dt = run_time - pd.to_timedelta(interval) * limit
        df_list = []
        data_len = 0
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': _limit,
            'startTime': int(time.mktime(start_time_dt.timetuple())) * 1000
        }

        while True:
            try:
                if symbol_type == 'swap':
                    kline = await async_retry_wrapper(
                        self.exchange.fapipublic_get_klines, params=params, func_name=f'获取{symbol}K线', if_exit=False
                    )
                else:
                    kline = await async_retry_wrapper(
                        self.exchange.public_get_klines, params=params, func_name=f'获取{symbol}K线', if_exit=False
                    )
            except Exception as e:
                print(f"Error fetching {symbol}: {e}")
                return pd.DataFrame()

            if not kline:
                break
            
            df = pd.DataFrame(kline, dtype='float')
            if df.empty:
                break

            columns = {0: 'candle_begin_time', 1: 'open', 2: 'high', 3: 'low', 4: 'close', 5: 'volume', 6: 'close_time',
                       7: 'quote_volume', 8: 'trade_num', 9: 'taker_buy_base_asset_volume', 10: 'taker_buy_quote_asset_volume',
                       11: 'ignore'}
            df.rename(columns=columns, inplace=True)
            df['candle_begin_time'] = pd.to_datetime(df['candle_begin_time'], unit='ms')
            
            # 优化：稍后进行排序和去重
            
            df_list.append(df)
            data_len += df.shape[0]

            if data_len >= limit:
                break
            
            last_time = int(df.iloc[-1]['candle_begin_time'].timestamp()) * 1000
            if params['startTime'] == last_time:
                break
            
            params['startTime'] = last_time
            # 异步 sleep 通常在这里不需要，因为我们要尽可能快，但为了安全起见：
            # await asyncio.sleep(0.01) 

        if not df_list:
            return pd.DataFrame()

        all_df = pd.concat(df_list, ignore_index=True)
        all_df['symbol'] = symbol
        all_df['symbol_type'] = symbol_type
        all_df.sort_values(by=['candle_begin_time'], inplace=True)
        all_df.drop_duplicates(subset=['candle_begin_time'], keep='last', inplace=True)

        all_df = all_df[all_df['candle_begin_time'] + pd.Timedelta(hours=self.utc_offset) < run_time]
        all_df.reset_index(drop=True, inplace=True)

        return all_df
