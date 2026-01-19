# -*- coding: utf-8 -*-
"""
九号布林策略 - 离线单元测试（只测“确定性逻辑”）

为什么只测这些（而不是跑真行情）？
    九号策略的实时部分依赖交易所 WebSocket（长连接，像电话一直不挂断）和真实行情，
    这类东西不适合放进 CI（持续集成：每次提交自动跑测试）里。

所以这里我们只测“纯数学/纯逻辑”的部分：
    - 1m -> 5m/15m 分桶是否对齐交易所周期
    - 未预热时不会乱发信号（避免启动就刷屏）
"""

from __future__ import annotations

import unittest

from 策略仓库.九号布林策略.program.strategy_brain import 分钟K线, 九号布林策略脑子, _周期聚合器


class Test九号布林策略聚合(unittest.TestCase):
    def test_5m分桶对齐与收盘标记(self) -> None:
        agg = _周期聚合器(周期分钟=5)

        # 0:00~0:04 这 5 根分钟线都属于同一个 5m 桶：0:00~0:05
        # - 桶起点 = 0
        # - 桶终点 = 300_000
        # - 第 5 根（i=4, end=300_000）应被标记为“刚好收盘”
        closed_flags: list[bool] = []
        bucket_starts: list[int] = []
        bucket_ends: list[int] = []

        for i in range(5):
            start_ms = i * 60_000
            end_ms = start_ms + 60_000
            k = 分钟K线(
                开始时间_ms=start_ms,
                结束时间_ms=end_ms,
                开=100.0,
                高=101.0,
                低=99.0,
                收=float(100.0 + i),
                量=1.0,
            )
            snap, closed = agg.更新并取快照(k)
            closed_flags.append(bool(closed))
            bucket_starts.append(int(snap.桶起点_ms))
            bucket_ends.append(int(snap.桶终点_ms))

        self.assertEqual(bucket_starts, [0, 0, 0, 0, 0])
        self.assertEqual(bucket_ends, [300_000, 300_000, 300_000, 300_000, 300_000])
        self.assertEqual(closed_flags, [False, False, False, False, True])
        self.assertEqual(len(agg.历史收盘价()), 1)

        # 下一分钟进入新桶：0:05~0:10
        k6 = 分钟K线(
            开始时间_ms=300_000,
            结束时间_ms=360_000,
            开=105.0,
            高=106.0,
            低=104.0,
            收=105.0,
            量=1.0,
        )
        snap6, closed6 = agg.更新并取快照(k6)
        self.assertEqual(int(snap6.桶起点_ms), 300_000)
        self.assertEqual(int(snap6.桶终点_ms), 600_000)
        self.assertEqual(bool(closed6), False)

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
            signals = 脑子.喂入一分钟K线并产出信号(k)
            self.assertEqual(signals, [])


if __name__ == "__main__":
    unittest.main()
