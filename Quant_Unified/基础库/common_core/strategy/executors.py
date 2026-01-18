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

from .interfaces import 执行器接口
from .models import K线, 账户状态, 成交回报, 策略输出, 限价挂单, 订单方向


@dataclass(slots=True)
class 撮合统计:
    """
    撮合统计信息（回测用）
    """

    成交次数: int = 0
    成交额: float = 0.0
    已实现盈亏: float = 0.0


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
        update_threshold_ratio: float = 0.05,
        价格偏离阈值: float = 0.5,
    ) -> None:
        self._交易对 = str(交易对)
        self._钱包余额 = float(初始资金)
        self._持仓数量 = float(初始持仓数量)
        self._持仓均价 = float(初始持仓均价) if 初始持仓数量 > 0 else 0.0
        self._最新价 = 0.0

        self._maker_fee = float(maker_fee)
        self._更新阈值 = float(update_threshold_ratio)
        self._价格偏离阈值 = float(价格偏离阈值)

        self._活跃买单: list[限价挂单] = []
        self._活跃卖单: list[限价挂单] = []

        self._上次网格宽度 = 0.0
        self._上次状态 = ""
        self._上次持仓数量: float | None = self._持仓数量

        self._统计 = 撮合统计()

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

    def 推进K线(self, k线: K线) -> list[成交回报]:
        """
        在一根 K 线内撮合“活跃挂单”，返回成交回报列表。
        """
        成交列表: list[成交回报] = []

        if not self._活跃买单 and not self._活跃卖单:
            self._最新价 = float(k线.收)
            return 成交列表

        开 = float(k线.开)
        高 = float(k线.高)
        低 = float(k线.低)
        收 = float(k线.收)
        时间戳 = int(k线.收盘时间_ms)

        # 1) 开盘跳空：价格直接跨过挂单
        成交列表.extend(self._撮合开盘跳空(开, 时间戳))

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

        self._最新价 = 收
        return 成交列表

    # =========================
    # 内部工具
    # =========================

    def _计算账户权益(self, 当前价: float) -> float:
        if self._持仓数量 != 0.0 and self._持仓均价 > 0.0:
            return self._钱包余额 + self._持仓数量 * (当前价 - self._持仓均价)
        return self._钱包余额

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

        if 订单.方向 == 订单方向.卖:
            if self._持仓数量 <= 0.0:
                return None
            if 成交量 > self._持仓数量:
                成交量 = float(self._持仓数量)
            if 成交量 <= 0.0:
                return None

        # 费用（默认 maker=0）
        成交额 = 成交价 * 成交量
        手续费 = abs(成交额) * self._maker_fee
        if 手续费 > 0:
            self._钱包余额 -= 手续费

        if 订单.方向 == 订单方向.买:
            新持仓 = self._持仓数量 + 成交量
            if 新持仓 > 0.0:
                if self._持仓数量 > 0.0 and self._持仓均价 > 0.0:
                    self._持仓均价 = (self._持仓数量 * self._持仓均价 + 成交量 * 成交价) / 新持仓
                else:
                    self._持仓均价 = 成交价
            self._持仓数量 = 新持仓
        else:
            已实现 = 成交量 * (成交价 - self._持仓均价)
            self._钱包余额 += 已实现
            self._统计.已实现盈亏 += 已实现
            self._持仓数量 -= 成交量
            if self._持仓数量 <= 0.0:
                self._持仓数量 = 0.0
                self._持仓均价 = 0.0

        self._统计.成交次数 += 1
        self._统计.成交额 += abs(成交额)

        return 成交回报(
            交易对=self._交易对,
            成交时间_ms=时间戳,
            成交价=float(成交价),
            成交量=float(成交量),
            方向=订单.方向,
            是否Maker=True,
        )
