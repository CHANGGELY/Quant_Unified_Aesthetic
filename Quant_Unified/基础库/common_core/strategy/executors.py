# -*- coding: utf-8 -*-
"""
common_core.strategy.executors - 回测执行器（把策略输出撮合到 K 线）

这个文件是干嘛的？
    你已经有了“策略脑子”（输出挂单），还需要一个“手脚”去执行：
    - 实盘执行器：对接真实交易所
    - 回测执行器：用 OHLC 模拟“挂单被价格撞上才成交”

为什么要放在公共层？
    这样每个策略只需要实现自己的“脑子”，回测/实盘只换执行器，
    避免“一套策略逻辑写两遍”的悲剧。

术语解释：
    - OHLC：开/高/低/收，像把一段“价格视频”压缩成 4 个关键帧。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .interfaces import 执行器接口
from .models import K线, 账户状态, 成交回报, 策略输出, 限价挂单, 订单方向, 目标仓位, 仓位方向
from ..risk_ctrl.liquidation import LiquidationChecker


@dataclass(slots=True)
class 撮合统计:
    """
    撮合统计信息（回测用）
    """

    成交次数: int = 0
    成交额: float = 0.0
    已实现盈亏: float = 0.0


@dataclass(slots=True)
class 调仓统计:
    """
    调仓统计信息（回测用）
    """

    调仓次数: int = 0
    成交额: float = 0.0
    交易成本: float = 0.0


class K线撮合执行器(执行器接口):
    """
    K线撮合执行器（单标的）

    核心逻辑：
        - 接收策略输出的限价挂单
        - 用 K 线 OHLC 路径判断哪些挂单会被“撞到”
        - 更新账户状态（保证金口径）
    """

    def __init__(
        self,
        交易对: str,
        初始资金: float,
        初始持仓数量: float = 0.0,
        初始持仓均价: float = 0.0,
        maker_fee: float = 0.0,
        最小维持保证金率: float = 0.005,
        update_threshold_ratio: float = 0.05,
        价格偏离阈值: float = 0.5,
        启用迟滞更新: bool = True,
    ) -> None:
        self._交易对 = str(交易对)
        self._钱包余额 = float(初始资金)
        self._持仓数量 = float(初始持仓数量)
        self._持仓均价 = float(初始持仓均价) if 初始持仓数量 > 0 else 0.0
        self._最新价 = 0.0

        self._maker_fee = float(maker_fee)
        self._风控 = LiquidationChecker(min_margin_rate=float(最小维持保证金率))
        self._更新阈值 = float(update_threshold_ratio)
        self._价格偏离阈值 = float(价格偏离阈值)
        self._启用迟滞更新 = bool(启用迟滞更新)

        self._活跃买单: list[限价挂单] = []
        self._活跃卖单: list[限价挂单] = []

        self._上次网格宽度 = 0.0
        self._上次状态 = ""
        self._上次持仓数量: float | None = self._持仓数量

        self._统计 = 撮合统计()
        self._是否爆仓: bool = False
        self._爆仓时间_ms: int | None = None
        self._爆仓价格: float | None = None

    # =========================
    # 执行器接口
    # =========================

    def 获取账户状态(self) -> 账户状态:
        当前价 = float(self._最新价)
        账户权益 = self._计算账户权益(当前价)
        未实现盈亏 = 0.0
        if self._持仓数量 != 0.0 and self._持仓均价 > 0.0:
            未实现盈亏 = self._持仓数量 * (当前价 - self._持仓均价)

        return 账户状态(
            交易对=self._交易对,
            账户权益=账户权益,
            可用余额=float(self._钱包余额),
            持仓数量=float(self._持仓数量),
            持仓均价=float(self._持仓均价),
            未实现盈亏=float(未实现盈亏),
        )

    def 执行策略输出(self, 输出: 策略输出) -> None:
        目标买单, 目标卖单 = self._拆分挂单(输出.目标挂单)

        备注 = 输出.备注 or {}
        当前宽度 = float(备注.get("grid_width", 0.0) or 0.0)
        当前状态 = str(备注.get("regime", "") or "")

        # ====== “完全跟随”模式：策略说挂什么就挂什么 ======
        # 说明：
        #   - 有些策略（例如经典网格）希望“每次输出都精确覆盖当前活跃挂单”
        #   - 迟滞更新属于“交易执行层的优化策略”，不应强行绑定到所有策略
        if not self._启用迟滞更新:
            self._活跃买单 = 目标买单
            self._活跃卖单 = 目标卖单
            self._上次持仓数量 = self._持仓数量
            self._上次网格宽度 = 当前宽度 if 当前宽度 > 0 else self._上次网格宽度
            self._上次状态 = 当前状态 or self._上次状态
            return

        # ====== 迟滞更新判断（对齐实盘思路）======
        需要更新 = False

        # 1) 成交后立刻补单（用“仓位变化”判断）
        if self._上次持仓数量 is not None and self._持仓数量 != self._上次持仓数量:
            需要更新 = True
        self._上次持仓数量 = self._持仓数量

        # 2) 网格宽度变化过大
        if not 需要更新 and self._上次网格宽度 > 0.0 and 当前宽度 > 0.0:
            diff_ratio = abs(当前宽度 - self._上次网格宽度) / self._上次网格宽度
            if diff_ratio > self._更新阈值:
                需要更新 = True

        # 3) SPIKE 状态积极更新
        if not 需要更新 and 当前状态.upper() == "SPIKE" and 当前宽度 != self._上次网格宽度:
            需要更新 = True

        # 4) 缺少挂单
        if not 需要更新 and not self._活跃买单 and 目标买单:
            需要更新 = True
        if not 需要更新 and not self._活跃卖单 and 目标卖单:
            需要更新 = True

        # 5) 价格偏离过大
        if not 需要更新:
            if self._活跃买单 and 目标买单:
                偏离 = abs(self._活跃买单[0].价格 - 目标买单[0].价格) / max(目标买单[0].价格, 1e-12)
                if 偏离 > self._价格偏离阈值:
                    需要更新 = True
            if not 需要更新 and self._活跃卖单 and 目标卖单:
                偏离 = abs(self._活跃卖单[0].价格 - 目标卖单[0].价格) / max(目标卖单[0].价格, 1e-12)
                if 偏离 > self._价格偏离阈值:
                    需要更新 = True

        # 6) 首次必挂
        if not self._活跃买单 and not self._活跃卖单:
            需要更新 = True

        if 需要更新:
            self._活跃买单 = 目标买单
            self._活跃卖单 = 目标卖单
            if 当前宽度 > 0.0:
                self._上次网格宽度 = 当前宽度
            if 当前状态:
                self._上次状态 = 当前状态

    # =========================
    # 回测辅助方法
    # =========================

    def 设置最新价(self, 价格: float) -> None:
        if 价格 > 0:
            self._最新价 = float(价格)

    def 获取成交统计(self) -> 撮合统计:
        return self._统计

    @property
    def 是否爆仓(self) -> bool:
        return bool(self._是否爆仓)

    @property
    def 爆仓时间_ms(self) -> int | None:
        return self._爆仓时间_ms

    @property
    def 爆仓价格(self) -> float | None:
        return self._爆仓价格

    def 推进K线(self, k线: K线) -> list[成交回报]:
        """
        在一根 K 线内撮合“活跃挂单”，返回成交回报列表。
        """
        成交列表: list[成交回报] = []

        if self._是否爆仓:
            return 成交列表

        if not self._活跃买单 and not self._活跃卖单:
            self._最新价 = float(k线.收)
            self._检查爆仓(float(k线.收), int(k线.收盘时间_ms))
            return 成交列表

        开 = float(k线.开)
        高 = float(k线.高)
        低 = float(k线.低)
        收 = float(k线.收)
        时间戳 = int(k线.收盘时间_ms)

        # 0) 先用开盘价做一次“最早的风险检查”（跳空可能直接把你打穿）
        self._检查爆仓(开, 时间戳)
        if self._是否爆仓:
            self._活跃买单 = []
            self._活跃卖单 = []
            self._最新价 = 收
            return 成交列表

        # 1) 开盘跳空：价格直接跨过挂单
        成交列表.extend(self._撮合开盘跳空(开, 时间戳))
        if self._是否爆仓:
            self._活跃买单 = []
            self._活跃卖单 = []
            self._最新价 = 收
            return 成交列表

        # 2) K 线内部路径撮合
        if 收 >= 开:
            路径 = (开, 低, 高, 收)
        else:
            路径 = (开, 高, 低, 收)

        for 起点, 终点 in zip(路径, 路径[1:]):
            if 终点 < 起点:
                成交列表.extend(self._撮合下跌段(起点, 终点, 时间戳))
            elif 终点 > 起点:
                成交列表.extend(self._撮合上涨段(起点, 终点, 时间戳))
            if self._是否爆仓:
                self._活跃买单 = []
                self._活跃卖单 = []
                self._最新价 = 收
                return 成交列表

            # 段终点做一次风险检查（足够覆盖“本段最差点”）
            self._检查爆仓(float(终点), 时间戳)
            if self._是否爆仓:
                self._活跃买单 = []
                self._活跃卖单 = []
                self._最新价 = 收
                return 成交列表

        self._最新价 = 收
        self._检查爆仓(收, 时间戳)
        return 成交列表

    # =========================
    # 内部工具
    # =========================

    def _计算账户权益(self, 当前价: float) -> float:
        if self._持仓数量 != 0.0 and self._持仓均价 > 0.0:
            return self._钱包余额 + self._持仓数量 * (当前价 - self._持仓均价)
        return self._钱包余额

    def _检查爆仓(self, 价格: float, 时间戳_ms: int) -> None:
        if self._是否爆仓:
            return
        价格 = float(价格)
        if 价格 <= 0.0:
            return

        if self._持仓数量 == 0.0:
            return

        持仓名义 = abs(self._持仓数量) * 价格
        账户权益 = self._计算账户权益(价格)
        is_liq, _ = self._风控.check_margin_rate(账户权益, 持仓名义)
        if not is_liq:
            return

        self._是否爆仓 = True
        self._爆仓时间_ms = int(时间戳_ms)
        self._爆仓价格 = float(价格)

        # 统一处理：爆仓后账户归零（便于指标/可视化“立刻看到死掉”）
        self._钱包余额 = 0.0
        self._持仓数量 = 0.0
        self._持仓均价 = 0.0

    @staticmethod
    def _拆分挂单(挂单列表: Iterable[限价挂单]) -> tuple[list[限价挂单], list[限价挂单]]:
        买单: list[限价挂单] = []
        卖单: list[限价挂单] = []
        for 挂单 in 挂单列表 or []:
            if 挂单.数量 <= 0 or 挂单.价格 <= 0:
                continue
            if 挂单.方向 == 订单方向.买:
                买单.append(挂单)
            else:
                卖单.append(挂单)

        买单.sort(key=lambda x: float(x.价格), reverse=True)
        卖单.sort(key=lambda x: float(x.价格))
        return 买单, 卖单

    def _撮合开盘跳空(self, 开盘价: float, 时间戳: int) -> list[成交回报]:
        成交列表: list[成交回报] = []

        if self._活跃买单:
            剩余买单: list[限价挂单] = []
            for 订单 in self._活跃买单:
                if 开盘价 <= 订单.价格:
                    成交 = self._执行成交(订单, float(订单.价格), float(订单.数量), 时间戳)
                    if 成交 is not None:
                        成交列表.append(成交)
                else:
                    剩余买单.append(订单)
            self._活跃买单 = 剩余买单

        if self._活跃卖单:
            剩余卖单: list[限价挂单] = []
            for 订单 in self._活跃卖单:
                if 开盘价 >= 订单.价格:
                    成交 = self._执行成交(订单, float(订单.价格), float(订单.数量), 时间戳)
                    if 成交 is not None:
                        成交列表.append(成交)
                else:
                    剩余卖单.append(订单)
            self._活跃卖单 = 剩余卖单

        return 成交列表

    def _撮合下跌段(self, 起点: float, 终点: float, 时间戳: int) -> list[成交回报]:
        if not self._活跃买单:
            return []
        if 终点 > 起点:
            return []

        成交列表: list[成交回报] = []
        剩余买单: list[限价挂单] = []
        for 订单 in self._活跃买单:
            价格 = float(订单.价格)
            if 终点 <= 价格 <= 起点:
                成交 = self._执行成交(订单, 价格, float(订单.数量), 时间戳)
                if 成交 is not None:
                    成交列表.append(成交)
            else:
                剩余买单.append(订单)

        self._活跃买单 = 剩余买单
        return 成交列表

    def _撮合上涨段(self, 起点: float, 终点: float, 时间戳: int) -> list[成交回报]:
        if not self._活跃卖单:
            return []
        if 终点 < 起点:
            return []

        成交列表: list[成交回报] = []
        剩余卖单: list[限价挂单] = []
        for 订单 in self._活跃卖单:
            价格 = float(订单.价格)
            if 起点 <= 价格 <= 终点:
                成交 = self._执行成交(订单, 价格, float(订单.数量), 时间戳)
                if 成交 is not None:
                    成交列表.append(成交)
            else:
                剩余卖单.append(订单)

        self._活跃卖单 = 剩余卖单
        return 成交列表

    def _执行成交(self, 订单: 限价挂单, 成交价: float, 成交量: float, 时间戳: int) -> 成交回报 | None:
        成交量 = float(成交量)
        if 成交量 <= 0.0:
            return None

        pos = float(self._持仓数量)
        avg = float(self._持仓均价)

        # 费用（默认 maker=0）
        # reduce_only：只允许减仓，不允许反手开新仓
        # 注意：当订单数量大于当前持仓时，交易所通常会“最多成交到 0”，多出来的部分会被拒绝/取消。
        #       所以在回测里，我们也把实际成交量裁切到可减仓范围内，避免“成交量虚报、手续费多扣”的问题。
        if bool(订单.只减仓):
            if 订单.方向 == 订单方向.买:
                if pos >= 0.0:
                    return None
                成交量 = min(成交量, abs(pos))
            else:
                if pos <= 0.0:
                    return None
                成交量 = min(成交量, pos)

            if 成交量 <= 0.0:
                return None

        成交额 = 成交价 * 成交量
        手续费 = abs(成交额) * self._maker_fee
        if 手续费 > 0:
            self._钱包余额 -= 手续费

        if 订单.方向 == 订单方向.买:
            if pos >= 0.0:
                # 加多 / 开多
                new_pos = pos + 成交量
                if pos == 0.0:
                    avg = 成交价
                else:
                    avg = (pos * avg + 成交量 * 成交价) / new_pos
                pos = new_pos
            else:
                # 平空（可能反手开多）
                short_abs = -pos
                close_qty = min(成交量, short_abs)
                已实现 = close_qty * (avg - 成交价)
                self._钱包余额 += 已实现
                self._统计.已实现盈亏 += 已实现
                pos += close_qty  # pos 负数变“更接近 0”
                remain = 成交量 - close_qty
                if abs(pos) < 1e-12:
                    pos = 0.0
                    avg = 0.0
                if remain > 0.0:
                    # 反手开多：剩余部分用本次成交价做成本
                    if not bool(订单.只减仓):
                        pos = remain
                        avg = 成交价
        else:
            if pos <= 0.0:
                # 加空 / 开空
                new_abs = abs(pos) + 成交量
                if pos == 0.0:
                    avg = 成交价
                else:
                    avg = (abs(pos) * avg + 成交量 * 成交价) / new_abs
                pos = -new_abs
            else:
                # 平多（可能反手开空）
                close_qty = min(成交量, pos)
                已实现 = close_qty * (成交价 - avg)
                self._钱包余额 += 已实现
                self._统计.已实现盈亏 += 已实现
                pos -= close_qty
                remain = 成交量 - close_qty
                if abs(pos) < 1e-12:
                    pos = 0.0
                    avg = 0.0
                if remain > 0.0:
                    # 反手开空：剩余部分用本次成交价做成本
                    if not bool(订单.只减仓):
                        pos = -remain
                        avg = 成交价

        self._持仓数量 = float(pos)
        self._持仓均价 = float(avg)

        self._统计.成交次数 += 1
        self._统计.成交额 += abs(成交额)

        # 成交后立刻做一次风险检查（比如：加仓后保证金率下降）
        self._检查爆仓(float(成交价), int(时间戳))

        return 成交回报(
            交易对=self._交易对,
            成交时间_ms=时间戳,
            成交价=float(成交价),
            成交量=float(成交量),
            方向=订单.方向,
            是否Maker=True,
        )


@dataclass(slots=True)
class 对冲撮合统计:
    """
    双向持仓（对冲模式）撮合统计信息（回测用）
    """

    成交次数: int = 0
    成交额: float = 0.0
    已实现盈亏: float = 0.0


class K线对冲撮合执行器(执行器接口):
    """
    K线对冲撮合执行器（单标的、双向持仓）

    适用场景：
        - 做市/对冲策略：同时持有多头和空头（对冲模式）
        - 策略输出的订单需要携带 `仓位方向`（LONG/SHORT）

    撮合规则：
        - 用 OHLC 路径模拟 K 线内价格运动（阳线：开->低->高->收；阴线：开->高->低->收）
        - 买单：价格下行撞到挂单价则成交
        - 卖单：价格上行撞到挂单价则成交

    爆仓检查：
        - 使用“保证金率 = 账户权益 / (多头名义+空头名义)”的保守口径
        - 低于最小维持保证金率则爆仓，账户归零
    """

    def __init__(
        self,
        交易对: str,
        初始资金: float,
        *,
        maker_fee: float = 0.0,
        最小维持保证金率: float = 0.005,
        启用迟滞更新: bool = False,
    ) -> None:
        self._交易对 = str(交易对)
        self._钱包余额 = float(初始资金)
        self._最新价 = 0.0

        # 双向持仓
        self._多头数量 = 0.0
        self._多头均价 = 0.0
        self._空头数量 = 0.0
        self._空头均价 = 0.0

        self._maker_fee = float(maker_fee)
        self._风控 = LiquidationChecker(min_margin_rate=float(最小维持保证金率))

        self._启用迟滞更新 = bool(启用迟滞更新)
        self._上次多头数量: float | None = None
        self._上次空头数量: float | None = None

        self._活跃买单: list[限价挂单] = []
        self._活跃卖单: list[限价挂单] = []

        self._统计 = 对冲撮合统计()

        self._是否爆仓: bool = False
        self._爆仓时间_ms: int | None = None
        self._爆仓价格: float | None = None

    # =========================
    # 执行器接口
    # =========================

    def 获取账户状态(self) -> 账户状态:
        当前价 = float(self._最新价)
        账户权益 = self._计算账户权益(当前价)
        未实现 = self._计算未实现盈亏(当前价)
        净持仓 = float(self._多头数量 - self._空头数量)
        # 净持仓均价在对冲模式下没有严格含义，这里给 0 以避免误用
        return 账户状态(
            交易对=self._交易对,
            账户权益=float(账户权益),
            可用余额=float(self._钱包余额),
            持仓数量=float(净持仓),
            持仓均价=0.0,
            未实现盈亏=float(未实现),
            多头持仓数量=float(self._多头数量),
            多头持仓均价=float(self._多头均价),
            空头持仓数量=float(self._空头数量),
            空头持仓均价=float(self._空头均价),
        )

    def 执行策略输出(self, 输出: 策略输出) -> None:
        if self._是否爆仓:
            return

        目标买单, 目标卖单 = self._拆分挂单(输出.目标挂单)

        if not self._启用迟滞更新:
            self._活跃买单 = 目标买单
            self._活跃卖单 = 目标卖单
            self._上次多头数量 = self._多头数量
            self._上次空头数量 = self._空头数量
            return

        需要更新 = False
        if self._上次多头数量 is not None and self._多头数量 != self._上次多头数量:
            需要更新 = True
        if self._上次空头数量 is not None and self._空头数量 != self._上次空头数量:
            需要更新 = True
        self._上次多头数量 = self._多头数量
        self._上次空头数量 = self._空头数量

        if not 需要更新 and (not self._活跃买单 or not self._活跃卖单):
            需要更新 = True

        if 需要更新:
            self._活跃买单 = 目标买单
            self._活跃卖单 = 目标卖单

    # =========================
    # 回测辅助方法
    # =========================

    def 设置最新价(self, 价格: float) -> None:
        if 价格 > 0:
            self._最新价 = float(价格)

    def 获取成交统计(self) -> 对冲撮合统计:
        return self._统计

    @property
    def 是否爆仓(self) -> bool:
        return bool(self._是否爆仓)

    @property
    def 爆仓时间_ms(self) -> int | None:
        return self._爆仓时间_ms

    @property
    def 爆仓价格(self) -> float | None:
        return self._爆仓价格

    def 推进K线(self, k线: K线) -> list[成交回报]:
        成交列表: list[成交回报] = []

        if self._是否爆仓:
            return 成交列表

        开 = float(k线.开)
        高 = float(k线.高)
        低 = float(k线.低)
        收 = float(k线.收)
        时间戳 = int(k线.收盘时间_ms)

        # 0) 开盘先做一次风险检查（跳空可能直接把你打穿）
        self._检查爆仓(开, 时间戳)
        if self._是否爆仓:
            self._活跃买单 = []
            self._活跃卖单 = []
            self._最新价 = 收
            return 成交列表

        # 没挂单：只更新价格并检查风险
        if not self._活跃买单 and not self._活跃卖单:
            self._最新价 = 收
            self._检查爆仓(收, 时间戳)
            return 成交列表

        # 1) 开盘跳空撮合
        成交列表.extend(self._撮合开盘跳空(开, 时间戳))
        if self._是否爆仓:
            self._活跃买单 = []
            self._活跃卖单 = []
            self._最新价 = 收
            return 成交列表

        # 2) K 线内部路径撮合
        if 收 >= 开:
            路径 = (开, 低, 高, 收)
        else:
            路径 = (开, 高, 低, 收)

        for 起点, 终点 in zip(路径, 路径[1:]):
            if 终点 < 起点:
                成交列表.extend(self._撮合下跌段(起点, 终点, 时间戳))
            elif 终点 > 起点:
                成交列表.extend(self._撮合上涨段(起点, 终点, 时间戳))

            if self._是否爆仓:
                self._活跃买单 = []
                self._活跃卖单 = []
                self._最新价 = 收
                return 成交列表

            # 段终点做一次风险检查
            self._检查爆仓(float(终点), 时间戳)
            if self._是否爆仓:
                self._活跃买单 = []
                self._活跃卖单 = []
                self._最新价 = 收
                return 成交列表

        self._最新价 = 收
        self._检查爆仓(收, 时间戳)
        return 成交列表

    # =========================
    # 内部工具
    # =========================

    def _计算未实现盈亏(self, 当前价: float) -> float:
        pnl = 0.0
        if self._多头数量 > 0.0 and self._多头均价 > 0.0:
            pnl += self._多头数量 * (当前价 - self._多头均价)
        if self._空头数量 > 0.0 and self._空头均价 > 0.0:
            pnl += self._空头数量 * (self._空头均价 - 当前价)
        return float(pnl)

    def _计算账户权益(self, 当前价: float) -> float:
        return float(self._钱包余额 + self._计算未实现盈亏(当前价))

    def _检查爆仓(self, 价格: float, 时间戳_ms: int) -> None:
        if self._是否爆仓:
            return
        价格 = float(价格)
        if 价格 <= 0.0:
            return

        if self._多头数量 <= 0.0 and self._空头数量 <= 0.0:
            return

        pos_val = (abs(self._多头数量) + abs(self._空头数量)) * 价格
        equity = self._计算账户权益(价格)
        is_liq, _ = self._风控.check_margin_rate(equity, pos_val)
        if not is_liq:
            return

        self._是否爆仓 = True
        self._爆仓时间_ms = int(时间戳_ms)
        self._爆仓价格 = float(价格)

        # 爆仓：账户归零
        self._钱包余额 = 0.0
        self._多头数量 = 0.0
        self._多头均价 = 0.0
        self._空头数量 = 0.0
        self._空头均价 = 0.0

    @staticmethod
    def _拆分挂单(挂单列表: Iterable[限价挂单]) -> tuple[list[限价挂单], list[限价挂单]]:
        买单: list[限价挂单] = []
        卖单: list[限价挂单] = []
        for 挂单 in 挂单列表 or []:
            if 挂单.数量 <= 0 or 挂单.价格 <= 0:
                continue
            # 对冲执行器要求明确仓位方向
            if 挂单.仓位方向 is None:
                raise ValueError("对冲撮合执行器要求挂单必须设置 仓位方向（LONG/SHORT）")
            if 挂单.仓位方向 == 仓位方向.空仓:
                continue
            if 挂单.方向 == 订单方向.买:
                买单.append(挂单)
            else:
                卖单.append(挂单)

        买单.sort(key=lambda x: float(x.价格), reverse=True)
        卖单.sort(key=lambda x: float(x.价格))
        return 买单, 卖单

    def _撮合开盘跳空(self, 开盘价: float, 时间戳: int) -> list[成交回报]:
        成交列表: list[成交回报] = []

        if self._活跃买单:
            剩余买单: list[限价挂单] = []
            for 订单 in self._活跃买单:
                if 开盘价 <= float(订单.价格):
                    成交 = self._执行成交(订单, float(订单.价格), float(订单.数量), 时间戳)
                    if 成交 is not None:
                        成交列表.append(成交)
                else:
                    剩余买单.append(订单)
            self._活跃买单 = 剩余买单

        if self._活跃卖单:
            剩余卖单: list[限价挂单] = []
            for 订单 in self._活跃卖单:
                if 开盘价 >= float(订单.价格):
                    成交 = self._执行成交(订单, float(订单.价格), float(订单.数量), 时间戳)
                    if 成交 is not None:
                        成交列表.append(成交)
                else:
                    剩余卖单.append(订单)
            self._活跃卖单 = 剩余卖单

        return 成交列表

    def _撮合下跌段(self, 起点: float, 终点: float, 时间戳: int) -> list[成交回报]:
        if not self._活跃买单:
            return []
        if 终点 > 起点:
            return []

        成交列表: list[成交回报] = []
        剩余买单: list[限价挂单] = []
        for 订单 in self._活跃买单:
            价格 = float(订单.价格)
            if 终点 <= 价格 <= 起点:
                成交 = self._执行成交(订单, 价格, float(订单.数量), 时间戳)
                if 成交 is not None:
                    成交列表.append(成交)
            else:
                剩余买单.append(订单)
        self._活跃买单 = 剩余买单
        return 成交列表

    def _撮合上涨段(self, 起点: float, 终点: float, 时间戳: int) -> list[成交回报]:
        if not self._活跃卖单:
            return []
        if 终点 < 起点:
            return []

        成交列表: list[成交回报] = []
        剩余卖单: list[限价挂单] = []
        for 订单 in self._活跃卖单:
            价格 = float(订单.价格)
            if 起点 <= 价格 <= 终点:
                成交 = self._执行成交(订单, 价格, float(订单.数量), 时间戳)
                if 成交 is not None:
                    成交列表.append(成交)
            else:
                剩余卖单.append(订单)
        self._活跃卖单 = 剩余卖单
        return 成交列表

    def _执行成交(self, 订单: 限价挂单, 成交价: float, 成交量: float, 时间戳: int) -> 成交回报 | None:
        成交量 = float(成交量)
        if 成交量 <= 0.0:
            return None

        成交价 = float(成交价)
        if 成交价 <= 0.0:
            return None

        仓位 = 订单.仓位方向
        if 仓位 not in (仓位方向.多, 仓位方向.空):
            raise ValueError(f"非法仓位方向: {仓位}")

        # 对冲模式下：同一张单只影响“自己的那条仓位边”（LONG 或 SHORT），不会反手开另一边。
        # 所以当你下“平仓单”但数量超过现有持仓时，真实交易所最多只会成交到 0。
        # 我们在回测里也用同样口径：把实际成交量裁切到当前可平的数量，避免成交量/手续费被高估。
        实际成交量 = float(成交量)
        if 仓位 == 仓位方向.多 and 订单.方向 == 订单方向.卖:
            if self._多头数量 <= 0.0:
                return None
            实际成交量 = min(实际成交量, float(self._多头数量))
        if 仓位 == 仓位方向.空 and 订单.方向 == 订单方向.买:
            if self._空头数量 <= 0.0:
                return None
            实际成交量 = min(实际成交量, float(self._空头数量))

        if 实际成交量 <= 0.0:
            return None

        # 手续费（默认 maker=0）
        成交额 = 成交价 * 实际成交量
        fee = abs(成交额) * self._maker_fee
        if fee > 0:
            self._钱包余额 -= fee

        已实现 = 0.0

        if 仓位 == 仓位方向.多:
            # 多头：BUY 增加，SELL 减少
            if 订单.方向 == 订单方向.买:
                new_qty = self._多头数量 + 实际成交量
                if self._多头数量 <= 0.0:
                    self._多头均价 = 成交价
                    self._多头数量 = new_qty
                else:
                    self._多头均价 = (self._多头数量 * self._多头均价 + 实际成交量 * 成交价) / new_qty
                    self._多头数量 = new_qty
            else:
                close_qty = float(实际成交量)
                已实现 = close_qty * (成交价 - float(self._多头均价))
                self._钱包余额 += 已实现
                self._多头数量 -= close_qty
                if self._多头数量 <= 1e-12:
                    self._多头数量 = 0.0
                    self._多头均价 = 0.0

        else:
            # 空头：SELL 增加，BUY 减少
            if 订单.方向 == 订单方向.卖:
                new_qty = self._空头数量 + 实际成交量
                if self._空头数量 <= 0.0:
                    self._空头均价 = 成交价
                    self._空头数量 = new_qty
                else:
                    self._空头均价 = (self._空头数量 * self._空头均价 + 实际成交量 * 成交价) / new_qty
                    self._空头数量 = new_qty
            else:
                close_qty = float(实际成交量)
                已实现 = close_qty * (float(self._空头均价) - 成交价)
                self._钱包余额 += 已实现
                self._空头数量 -= close_qty
                if self._空头数量 <= 1e-12:
                    self._空头数量 = 0.0
                    self._空头均价 = 0.0

        self._统计.成交次数 += 1
        self._统计.成交额 += abs(成交额)
        self._统计.已实现盈亏 += float(已实现)

        # 成交后立刻做一次风险检查
        self._检查爆仓(float(成交价), int(时间戳))

        return 成交回报(
            交易对=self._交易对,
            成交时间_ms=int(时间戳),
            成交价=float(成交价),
            成交量=float(实际成交量),
            方向=订单.方向,
            是否Maker=True,
            仓位方向=仓位,
        )


class K线调仓执行器(执行器接口):
    """
    K线调仓执行器（单标的）

    适用场景：
        - MACD、均线、VWAP 这类“每根K线收盘决定仓位方向”的策略
        - 预测策略（5号）输出多/空/空仓信号

    交易假设（可配置）：
        - 每根K线用收盘价做 mark-to-market（结算浮动盈亏）
        - 当策略要求换向时，在收盘附近成交（用 slippage 模拟滑点/点差）
        - 扣除手续费/滑点
        - 做爆仓检查：保证金率 < 最小维持保证金率 -> 归零
    """

    def __init__(
        self,
        交易对: str,
        初始资金: float,
        *,
        数量步进: float,
        手续费率: float,
        滑点率: float,
        最小下单名义: float = 0.0,
        最小维持保证金率: float = 0.005,
    ) -> None:
        if 数量步进 <= 0:
            raise ValueError(f"数量步进 必须 > 0, 当前={数量步进}")
        if 手续费率 < 0 or 滑点率 < 0:
            raise ValueError(f"手续费率/滑点率 必须 >= 0, 当前 fee={手续费率}, slippage={滑点率}")
        if 初始资金 < 0:
            raise ValueError(f"初始资金 必须 >= 0, 当前={初始资金}")

        self._交易对 = str(交易对)
        self._数量步进 = float(数量步进)
        self._手续费率 = float(手续费率)
        self._滑点率 = float(滑点率)
        self._最小下单名义 = float(最小下单名义)
        self._风控 = LiquidationChecker(min_margin_rate=float(最小维持保证金率))

        self._最新价 = 0.0
        self._上次结算价 = 0.0
        self._最新时间_ms: int | None = None
        self._账户权益 = float(初始资金)
        self._持仓数量 = 0.0
        self._持仓均价 = 0.0

        self._统计 = 调仓统计()
        self._是否爆仓 = False
        self._爆仓时间_ms: int | None = None
        self._爆仓价格: float | None = None

    # =========================
    # 执行器接口
    # =========================

    def 获取账户状态(self) -> 账户状态:
        未实现盈亏 = 0.0
        if self._持仓数量 != 0.0 and self._持仓均价 > 0.0 and self._最新价 > 0.0:
            未实现盈亏 = self._持仓数量 * (self._最新价 - self._持仓均价)

        return 账户状态(
            交易对=self._交易对,
            账户权益=float(self._账户权益),
            可用余额=float(self._账户权益),  # 这里不细分“可用/占用”，保持策略层最小口径
            持仓数量=float(self._持仓数量),
            持仓均价=float(self._持仓均价),
            未实现盈亏=float(未实现盈亏),
        )

    def 执行策略输出(self, 输出: 策略输出) -> None:
        if self._是否爆仓:
            return

        目标 = 输出.目标仓位
        if 目标 is None:
            return

        if self._最新价 <= 0.0:
            return

        目标 = self._归一化目标仓位(目标)
        if 目标.方向 == 仓位方向.空仓:
            目标数量 = 0.0
        else:
            sign = 1.0 if 目标.方向 == 仓位方向.多 else -1.0
            名义杠杆 = float(目标.名义杠杆)
            if 名义杠杆 < 0:
                return
            目标名义 = self._账户权益 * 名义杠杆
            raw_qty = sign * (目标名义 / self._最新价)
            目标数量 = self._按步进截断(raw_qty)
            if abs(目标数量) * self._最新价 < self._最小下单名义:
                目标数量 = 0.0

        delta = 目标数量 - self._持仓数量
        if abs(delta) <= 0.0:
            return

        # 执行价：用 slippage 把成交价往不利方向“推一点”
        exec_p = self._最新价 * (1.0 + self._滑点率) if delta > 0 else self._最新价 * (1.0 - self._滑点率)
        if exec_p <= 0.0:
            return

        turnover = abs(delta) * exec_p
        exec_impact = abs(delta) * abs(exec_p - self._最新价)
        tc = turnover * (self._手续费率 + self._滑点率)

        self._账户权益 -= (exec_impact + tc)
        self._统计.调仓次数 += 1
        self._统计.成交额 += float(turnover)
        self._统计.交易成本 += float(exec_impact + tc)

        # 更新持仓（简化：按执行价当作新的持仓均价，或做加权）
        self._更新持仓(delta_qty=delta, exec_price=exec_p)

        # 调仓后立即检查爆仓
        self._检查爆仓(self._最新价, self._最新时间_ms)

    # =========================
    # 回测辅助方法
    # =========================

    def 推进K线结算(self, k线: K线) -> None:
        """
        用收盘价做一次结算（mark-to-market）
        """
        if self._是否爆仓:
            self._最新价 = float(k线.收)
            return

        price = float(k线.收)
        if price <= 0:
            return

        if self._上次结算价 > 0.0:
            self._账户权益 += (price - self._上次结算价) * self._持仓数量
        self._上次结算价 = price
        self._最新价 = price
        self._最新时间_ms = int(k线.收盘时间_ms)

        self._检查爆仓(price, self._最新时间_ms)

    def 获取调仓统计(self) -> 调仓统计:
        return self._统计

    @property
    def 是否爆仓(self) -> bool:
        return bool(self._是否爆仓)

    @property
    def 爆仓时间_ms(self) -> int | None:
        return self._爆仓时间_ms

    @property
    def 爆仓价格(self) -> float | None:
        return self._爆仓价格

    # =========================
    # 内部工具
    # =========================

    def _按步进截断(self, raw_qty: float) -> float:
        step = self._数量步进
        lots = float(np.floor(abs(raw_qty) / step))
        return float(np.sign(raw_qty) * lots * step)

    def _归一化目标仓位(self, 目标: 目标仓位) -> 目标仓位:
        方向 = 目标.方向
        if 方向 not in (仓位方向.多, 仓位方向.空, 仓位方向.空仓):
            方向 = 仓位方向.空仓
        名义杠杆 = float(目标.名义杠杆)
        if 名义杠杆 < 0:
            名义杠杆 = 0.0
        return 目标仓位(交易对=self._交易对, 方向=方向, 名义杠杆=名义杠杆)

    def _更新持仓(self, *, delta_qty: float, exec_price: float) -> None:
        new_qty = self._持仓数量 + float(delta_qty)
        if abs(new_qty) <= 0.0:
            self._持仓数量 = 0.0
            self._持仓均价 = 0.0
            return

        # 方向翻转：均价直接用本次执行价
        if self._持仓数量 == 0.0:
            self._持仓均价 = float(exec_price)
            self._持仓数量 = float(new_qty)
            return

        prev_sign = 1.0 if self._持仓数量 > 0 else -1.0
        new_sign = 1.0 if new_qty > 0 else -1.0
        if prev_sign != new_sign:
            self._持仓均价 = float(exec_price)
            self._持仓数量 = float(new_qty)
            return

        # 同方向加减仓：用加权平均（减仓不会影响剩余部分成本，但这里用统一公式足够稳定）
        prev_val = abs(self._持仓数量) * float(self._持仓均价)
        delta_val = abs(delta_qty) * float(exec_price)
        total_qty = abs(new_qty)
        if total_qty > 0.0:
            self._持仓均价 = float((prev_val + delta_val) / total_qty)
        self._持仓数量 = float(new_qty)

    def _检查爆仓(self, mark_price: float, 时间戳_ms: int | None) -> None:
        if self._是否爆仓:
            return
        if mark_price <= 0.0:
            return
        if self._持仓数量 == 0.0:
            return

        pos_val = abs(self._持仓数量) * float(mark_price)
        is_liq, _ = self._风控.check_margin_rate(self._账户权益, pos_val)
        if not is_liq:
            return

        self._是否爆仓 = True
        self._爆仓时间_ms = int(时间戳_ms) if 时间戳_ms is not None else None
        self._爆仓价格 = float(mark_price)
        self._账户权益 = 0.0
        self._持仓数量 = 0.0
        self._持仓均价 = 0.0
