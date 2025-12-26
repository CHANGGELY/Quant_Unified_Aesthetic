#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest
from Quant_Unified.基础库.common_core.utils.orderbook_replay import OrderBook

class TestOrderBookReplay(unittest.TestCase):
    def setUp(self):
        self.ob = OrderBook("BTCUSDT")

    def test_apply_delta_basic(self):
        # 增加买单
        self.ob.apply_delta("buy", 6000000, 1000)
        self.ob.apply_delta("buy", 6000100, 2000)
        
        # 增加卖单
        self.ob.apply_delta("sell", 6000200, 1500)
        self.ob.apply_delta("sell", 6000300, 2500)
        
        snap = self.ob.get_snapshot(depth=5)
        
        # 验证排序: Bids 应该降序
        self.assertEqual(snap['bids'][0][0], 6000100)
        self.assertEqual(snap['bids'][1][0], 6000000)
        
        # 验证排序: Asks 应该升序
        self.assertEqual(snap['asks'][0][0], 6000200)
        self.assertEqual(snap['asks'][1][0], 6000300)

    def test_update_and_delete(self):
        self.ob.apply_delta("buy", 6000000, 1000)
        # 更新
        self.ob.apply_delta("buy", 6000000, 5000)
        self.assertEqual(self.ob.bids[6000000], 5000)
        
        # 删除
        self.ob.apply_delta("buy", 6000000, 0)
        self.assertNotIn(6000000, self.ob.bids)

    def test_flat_snapshot(self):
        self.ob.apply_delta("bid", 100, 10)
        self.ob.apply_delta("ask", 110, 20)
        
        flat = self.ob.get_flat_snapshot(depth=2)
        self.assertEqual(flat['bid1_p'], 100)
        self.assertEqual(flat['bid1_q'], 10)
        self.assertEqual(flat['ask1_p'], 110)
        self.assertEqual(flat['ask1_q'], 20)
        # 深度不够的应该补 0
        self.assertEqual(flat['bid2_p'], 0)

if __name__ == '__main__':
    unittest.main()
