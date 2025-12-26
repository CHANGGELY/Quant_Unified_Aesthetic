
import unittest
from common_core.risk_ctrl.liquidation import LiquidationChecker

class TestLiquidationChecker(unittest.TestCase):
    def setUp(self):
        self.checker = LiquidationChecker(min_margin_rate=0.005)

    def test_safe_state(self):
        # 权益 10000, 持仓 10000 -> 保证金率 100% -> 安全
        is_liq, rate = self.checker.check_margin_rate(10000, 10000)
        self.assertFalse(is_liq)
        self.assertEqual(rate, 1.0)

    def test_warning_state(self):
        # 权益 100, 持仓 10000 -> 保证金率 1% -> 安全但危险
        is_liq, rate = self.checker.check_margin_rate(100, 10000)
        self.assertFalse(is_liq)
        self.assertEqual(rate, 0.01)

    def test_liquidation_state(self):
        # 权益 40, 持仓 10000 -> 保证金率 0.4% < 0.5% -> 爆仓
        is_liq, rate = self.checker.check_margin_rate(40, 10000)
        self.assertTrue(is_liq)
        self.assertEqual(rate, 0.004)

    def test_zero_position(self):
        # 无持仓
        is_liq, rate = self.checker.check_margin_rate(10000, 0)
        self.assertFalse(is_liq)
        self.assertEqual(rate, 999.0)

if __name__ == '__main__':
    unittest.main()
