# -*- coding: utf-8 -*-
"""
九号布林策略 - 离线单元测试（只测“聚合/调度”这种确定性逻辑）

为什么只测这些？
    九号策略的实时部分依赖交易所 WebSocket（长连接）和真实行情，
    这类东西不适合放进 CI（持续集成：每次提交自动跑测试）里。

所以这里我们只测“纯数学/纯逻辑”的部分：
    - 1m -> 5m/15m 聚合是否按时收盘
    - 未预热时不会乱发信号（避免启动就刷屏）
"""

from __future__ import annotations

import unittest

from 策略仓库.九号布林策略.program.strategy_brain import 分钟K线, 九号布林策略脑子


class Test九号布林策略聚合(unittest.TestCase):
    def test_5m与15m按时收盘(self) -> None:
        脑子 = 九号布林策略脑子(
            交易对="TEST",
            布林窗口=3,  # 测试用小窗口，避免喂太多数据
            布林倍数=2.0,
            回看根数=5,
            阈值_15m_ma收敛=500,
            阈值_30m_ma收敛=1000,
            阈值_1h_ma收敛_上穿=1800,
            阈值_1h_ma收敛_下穿=1500,
            阈值_4h_ma收敛=1800,
            阈值_1d_ma收敛=2900,
        )

        # 喂入 15 分钟的 1m（0:00~0:15），检查：
        # - 5m K线应在 0:05、0:10、0:15 收盘（结束时间_ms=300k/600k/900k）
        # - 15m K线应在 0:15 收盘（结束时间_ms=900k）
        收盘_5m: list[int] = []
        收盘_15m: list[int] = []

        for i in range(15):
            start_ms = i * 60_000
            end_ms = start_ms + 60_000
            k = 分钟K线(
                开始时间_ms=start_ms,
                结束时间_ms=end_ms,
                开=100.0,
                高=101.0,
                低=99.0,
                收=100.0,
                量=1.0,
            )
            closed = 脑子.喂入一分钟K线(k)
            for tf, bar in closed:
                if tf == "5m":
                    收盘_5m.append(int(bar.结束时间_ms))
                if tf == "15m":
                    收盘_15m.append(int(bar.结束时间_ms))

        self.assertEqual(收盘_5m, [300_000, 600_000, 900_000])
        self.assertEqual(收盘_15m, [900_000])

    def test_未预热不会乱发信号(self) -> None:
        脑子 = 九号布林策略脑子(
            交易对="TEST",
            布林窗口=20,  # 用真实默认
            布林倍数=2.0,
            回看根数=5,
            阈值_15m_ma收敛=500,
            阈值_30m_ma收敛=1000,
            阈值_1h_ma收敛_上穿=1800,
            阈值_1h_ma收敛_下穿=1500,
            阈值_4h_ma收敛=1800,
            阈值_1d_ma收敛=2900,
        )

        # 喂 6 分钟数据，理论上：
        # - 布林窗口没满
        # - MA60 更不可能满
        # 所以不会产生任何推送信号
        for i in range(6):
            start_ms = i * 60_000
            end_ms = start_ms + 60_000
            k = 分钟K线(
                开始时间_ms=start_ms,
                结束时间_ms=end_ms,
                开=100.0,
                高=101.0,
                低=99.0,
                收=100.0,
                量=1.0,
            )
            closed = 脑子.喂入一分钟K线(k)
            signals = 脑子.处理已收盘周期K线并产出信号(closed)
            self.assertEqual(signals, [])


if __name__ == "__main__":
    unittest.main()

