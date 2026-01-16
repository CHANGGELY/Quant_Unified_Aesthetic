import unittest
from datetime import datetime

from 策略仓库.二号网格策略.program.step2_strategy import GridStrategy


class TestProgramGridStrategy(unittest.TestCase):
    def setUp(self):
        # 使用固定区间，避免动态 price_range 干扰
        self.cfg = {
            'symbol': 'ETHUSDT',
            'money': 10000,
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
            'price_range': 0,
        }
        self.s = GridStrategy(self.cfg)
        # 初始化当前价与网格
        self.s.on_tick(datetime.now(), 150)
        self.s.init()

    def test_central_and_interval(self):
        self.assertGreater(self.s.grid_dict['interval'], 0)
        c = self.s.grid_dict['price_central']
        self.assertTrue(self.s.min_price <= c <= self.s.max_price)

    def test_up_down_prices(self):
        c = self.s.grid_dict['price_central']
        up = self.s.get_up_price(c)
        down = self.s.get_down_price(c)
        self.assertGreater(up, c)
        self.assertLess(down, c)

    def test_pair_profit_buy_close_short(self):
        # 构造一次 SELL 后的 BUY 配对（先做空，后买入）
        # 先模拟触发 SELL 进入空头
        up = self.s.account_dict['up_price']
        self.s.update_price(datetime.now(), up + 1e-4)  # 触发 SELL
        # 再触发 BUY 配对
        down = self.s.account_dict['down_price']
        before_pair = self.s.account_dict['pair_profit']
        self.s.update_price(datetime.now(), down - 1e-4)  # 触发 BUY
        after_pair = self.s.account_dict['pair_profit']
        self.assertGreater(after_pair, before_pair)

    def test_shift_up_when_break_max(self):
        # 超过上限触发上移
        prev_max = self.s.grid_dict['max_price']
        self.s.update_order(datetime.now(), prev_max * 1.01, 'SELL')
        self.assertEqual(self.s.upward_shift_count, 1)
        self.assertGreater(self.s.grid_dict['max_price'], prev_max)


if __name__ == '__main__':
    unittest.main()
