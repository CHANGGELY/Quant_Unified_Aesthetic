"""
tests/test_grid.py - 单元测试（unittest：Python 自带的测试框架）

这个文件是干嘛的？
    验证旧版 `grid/grid_backtest.py` 里的 GridStrategy 是否能正常初始化、触发网格更新、触发上移逻辑。

怎么用？
    在仓库根目录运行：
        python3 -m unittest Quant_Unified/策略仓库/二号网格策略/tests/test_grid.py
"""

import sys
from pathlib import Path

# 让 `import 策略仓库...` 能找到 Quant_Unified 这个根目录
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # Quant_Unified
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import unittest
import pandas as pd
from datetime import datetime
from pytz import timezone

from 策略仓库.二号网格策略.core.engine import BacktestEngine
from 策略仓库.二号网格策略.grid.grid_backtest import GridStrategy

class MockStrategy(GridStrategy):
    def __init__(self, config):
        # Create minimal valid config for testing
        super().__init__(config)

class TestGridBacktest(unittest.TestCase):
    def setUp(self):
        self.config = {
            'symbol': 'ETHUSDT',
            'money': 1000,
            'leverage': 1,
            'interval_mode': 'geometric_sequence',
            'direction_mode': 'neutral',
            'capital_ratio': 1.0,
            'enable_upward_shift': True,
            'enable_downward_shift': True,
            'stop_up_price': 0,
            'stop_down_price': 0,
            'num_steps': 10,
            'min_price': 100,
            'max_price': 200,
            'price_range': 0
        }
        self.strategy = GridStrategy(self.config)
        self.strategy.curr_price = 150
        self.strategy.init() # Initialize grid

    def test_initialization(self):
        self.assertEqual(self.strategy.grid_dict['min_price'], 100)
        self.assertEqual(self.strategy.grid_dict['max_price'], 200)
        # Check central price is set reasonably
        self.assertTrue(100 <= self.strategy.grid_dict['price_central'] <= 200)

    def test_grid_update(self):
        # Initial state
        initial_grids = self.strategy.account_dict['positions_grids']
        
        # Price moves up -> Sell
        # Trigger an update
        up_price = self.strategy.account_dict['up_price']
        self.strategy.update_price(datetime.now(), up_price + 0.1)
        
        # Check if sold
        self.assertEqual(self.strategy.account_dict['positions_grids'], initial_grids - 1)

    def test_shift_logic(self):
        # Force price above max to trigger shift
        new_price = 205
        # Set current price near max to avoid jump
        self.strategy.curr_price = 200
        
        # Update
        self.strategy.update_order(datetime.now(), new_price, 'SELL')
        
        # Check shift count
        self.assertEqual(self.strategy.upward_shift_count, 1)

if __name__ == '__main__':
    unittest.main()
