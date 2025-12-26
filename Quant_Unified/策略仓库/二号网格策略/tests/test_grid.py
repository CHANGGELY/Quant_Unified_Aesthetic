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
