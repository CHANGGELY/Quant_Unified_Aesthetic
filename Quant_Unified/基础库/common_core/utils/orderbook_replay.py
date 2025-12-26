#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
L2 订单簿重放引擎
功能：根据增量更新（Delta）维护内存中的盘口状态，并支持快照提取。
支持价格和数量的整数存储以提高性能。
"""

from sortedcontainers import SortedDict
import logging

logger = logging.getLogger(__name__)

class OrderBook:
    def __init__(self, symbol: str):
        self.symbol = symbol
        # bids 降序排列 (最高价在最前)
        self.bids = SortedDict(lambda x: -x)
        # asks 升序排列 (最低价在最前)
        self.asks = SortedDict()
        self.last_update_id = 0
        self.timestamp = None

    def apply_delta(self, side: str, price_int: int, amount_int: int):
        """
        应用单条增量更新
        :param side: 'buy' 或 'sell' (Tardis 格式) 或 'bid'/'ask'
        :param price_int: 整数价格
        :param amount_int: 整数数量 (为 0 表示删除该档位)
        """
        target_dict = self.bids if side in ['buy', 'bid'] else self.asks
        
        if amount_int <= 0:
            target_dict.pop(price_int, None)
        else:
            target_dict[price_int] = amount_int

    def reset(self):
        """重置盘口"""
        self.bids.clear()
        self.asks.clear()

    def get_snapshot(self, depth: int = 50) -> dict:
        """
        获取当前盘口的快照
        :param depth: 档位深度
        :return: 包含 bids 和 asks 列表的字典
        """
        bid_keys = list(self.bids.keys())[:depth]
        bid_list = [(p, self.bids[p]) for p in bid_keys]
            
        ask_keys = list(self.asks.keys())[:depth]
        ask_list = [(p, self.asks[p]) for p in ask_keys]
            
        return {
            "symbol": self.symbol,
            "bids": bid_list,
            "asks": ask_list
        }

    def get_flat_snapshot(self, depth: int = 50) -> dict:
        """
        获取打平的快照格式，方便直接喂给模型 (例如 bid1_p, bid1_q ...)
        """
        result = {}
        
        bid_keys = list(self.bids.keys())
        # 处理 Bids
        for i in range(depth):
            if i < len(bid_keys):
                price = bid_keys[i]
                amount = self.bids[price]
                result[f"bid{i+1}_p"] = price
                result[f"bid{i+1}_q"] = amount
            else:
                result[f"bid{i+1}_p"] = 0
                result[f"bid{i+1}_q"] = 0
                
        ask_keys = list(self.asks.keys())
        # 处理 Asks
        for i in range(depth):
            if i < len(ask_keys):
                price = ask_keys[i]
                amount = self.asks[price]
                result[f"ask{i+1}_p"] = price
                result[f"ask{i+1}_q"] = amount
            else:
                result[f"ask{i+1}_p"] = 0
                result[f"ask{i+1}_q"] = 0
                
        return result
