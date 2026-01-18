# -*- coding: utf-8 -*-
"""
三号对冲策略 - 策略脑子（策略接口版）

这个文件是干嘛的？
    把“3号对冲策略”的想法，包装成 common_core.strategy 的统一接口：
        - 输入：K线收盘价 / 账户状态
        - 输出：我想挂哪些单（包含：开仓挂单 + 止盈挂单）

你可以把它想成：
    - 策略脑子：只负责说“我想要哪些挂单”
    - 执行器：负责把挂单用 K 线 OHLC 撮合成交，并做爆仓检测

重要约定（对冲模式）：
    - 我们允许同时持有多头(LONG)和空头(SHORT)
    - 所以每一张单都必须带 `仓位方向`，否则执行器会直接报错
"""

from __future__ import annotations

from dataclasses import dataclass

from 基础库.common_core.strategy import K线, 账户状态, 成交回报, 仓位方向, 策略输出, 限价挂单, 订单方向
from 策略仓库.三号对冲策略.config import Config


@dataclass(slots=True)
class 三号对冲策略状态:
    基准价: float | None = None


class 三号对冲策略脑子:
    """
    3号对冲策略脑子（统一策略接口版）

    当前版本的策略要点（更贴近“实盘挂单”的可执行模型）：
        - 以 `基准价` 为中心，向上/向下生成网格价位
        - 下方挂 BUY+LONG（逢低加多），上方挂 SELL+SHORT（逢高加空）
        - 有多仓就挂 SELL+LONG 做止盈；有空仓就挂 BUY+SHORT 做止盈
        - 当价格远离基准价时，自动把基准价移动到当前价（避免网格脱离行情）
    """

    策略名称 = "3号对冲策略"

    def __init__(self, 配置: Config | dict) -> None:
        if isinstance(配置, Config):
            self._配置 = 配置
        else:
            self._配置 = Config(**dict(配置))
        self._状态 = 三号对冲策略状态()

    # =========================
    # 策略接口
    # =========================

    def 在K线收盘(self, k线: K线, 账户: 账户状态) -> 策略输出:
        最新价 = float(k线.收)
        if 最新价 <= 0.0:
            return 策略输出()

        g = float(getattr(self._配置, "grid_percent", 0.0) or 0.0)
        if g <= 0.0:
            return 策略输出()

        levels = int(getattr(self._配置, "grid_levels", 0) or 0)
        if levels <= 0:
            return 策略输出()

        # 1) 初始化基准价
        if self._状态.基准价 is None:
            self._状态.基准价 = 最新价

        基准价 = float(self._状态.基准价)
        if 基准价 <= 0.0:
            基准价 = 最新价
            self._状态.基准价 = 最新价

        # 2) 如果价格跑太远，基准价跟随（避免网格“挂在天边”）
        上边界 = 基准价 * (1.0 + g * levels)
        下边界 = 基准价 * (1.0 - g * levels)
        if 最新价 > 上边界 or 最新价 < 下边界:
            基准价 = 最新价
            self._状态.基准价 = 最新价

        return self._生成挂单(基准价=基准价, 最新价=最新价, 账户=账户)

    def 在成交回报(self, 回报: 成交回报) -> None:
        # 只在“开仓成交”时移动基准价（更像经典网格：成交点就是新的中心）
        try:
            if 回报.仓位方向 == 仓位方向.多 and 回报.方向 == 订单方向.买:
                self._状态.基准价 = float(回报.成交价)
            elif 回报.仓位方向 == 仓位方向.空 and 回报.方向 == 订单方向.卖:
                self._状态.基准价 = float(回报.成交价)
        except Exception:
            return

    # =========================
    # 内部工具
    # =========================

    def _生成挂单(self, *, 基准价: float, 最新价: float, 账户: 账户状态) -> 策略输出:
        cfg = self._配置
        symbol = str(getattr(cfg, "symbol", "") or "UNKNOWN").upper()

        g = float(getattr(cfg, "grid_percent", 0.0) or 0.0)
        levels = int(getattr(cfg, "grid_levels", 0) or 0)

        post_only = bool(getattr(cfg, "post_only", True))
        tick = float(getattr(cfg, "tick_size", 0.01) or 0.01)
        off_buy = int(getattr(cfg, "post_only_tick_offset_buy", 1) or 1)
        off_sell = int(getattr(cfg, "post_only_tick_offset_sell", 1) or 1)

        初始多头单量 = float(getattr(cfg, "initial_long_size", 0.0) or 0.0)
        初始空头单量 = float(getattr(cfg, "initial_short_size", 0.0) or 0.0)

        max_side = getattr(cfg, "max_individual_position_size", None)
        最大单边 = float(max_side) if max_side is not None else None

        long_pos = float(getattr(账户, "多头持仓数量", 0.0) or 0.0)
        short_pos = float(getattr(账户, "空头持仓数量", 0.0) or 0.0)
        long_avg = float(getattr(账户, "多头持仓均价", 0.0) or 0.0)
        short_avg = float(getattr(账户, "空头持仓均价", 0.0) or 0.0)

        目标挂单: list[限价挂单] = []

        # ====== 1) 开仓挂单：下方加多，上方加空 ======
        can_open_long = 初始多头单量 > 0.0 and (最大单边 is None or long_pos < 最大单边 - 1e-12)
        can_open_short = 初始空头单量 > 0.0 and (最大单边 is None or short_pos < 最大单边 - 1e-12)

        if can_open_long:
            qty = 初始多头单量
            if 最大单边 is not None:
                qty = min(qty, max(0.0, 最大单边 - long_pos))
            for i in range(1, levels + 1):
                raw = 基准价 * (1.0 - g * i)
                price = raw - tick * off_buy if post_only else raw
                if price <= 0.0:
                    continue
                目标挂单.append(
                    限价挂单(
                        交易对=symbol,
                        方向=订单方向.买,
                        价格=float(price),
                        数量=float(qty),
                        只做挂单=post_only,
                        只减仓=False,
                        仓位方向=仓位方向.多,
                    )
                )

        if can_open_short:
            qty = 初始空头单量
            if 最大单边 is not None:
                qty = min(qty, max(0.0, 最大单边 - short_pos))
            for i in range(1, levels + 1):
                raw = 基准价 * (1.0 + g * i)
                price = raw + tick * off_sell if post_only else raw
                if price <= 0.0:
                    continue
                目标挂单.append(
                    限价挂单(
                        交易对=symbol,
                        方向=订单方向.卖,
                        价格=float(price),
                        数量=float(qty),
                        只做挂单=post_only,
                        只减仓=False,
                        仓位方向=仓位方向.空,
                    )
                )

        # ====== 2) 止盈挂单：有仓位就挂“只减仓” ======
        # 说明：止盈价用“一格距离”，数量用“每次平一小份”，避免一次性把仓位全清光
        if long_pos > 0.0 and long_avg > 0.0:
            close_qty = min(long_pos, max(初始多头单量, 0.0))
            if close_qty > 0.0:
                raw = long_avg * (1.0 + g)
                price = raw + tick * off_sell if post_only else raw
                目标挂单.append(
                    限价挂单(
                        交易对=symbol,
                        方向=订单方向.卖,
                        价格=float(price),
                        数量=float(close_qty),
                        只做挂单=post_only,
                        只减仓=True,
                        仓位方向=仓位方向.多,
                    )
                )

        if short_pos > 0.0 and short_avg > 0.0:
            close_qty = min(short_pos, max(初始空头单量, 0.0))
            if close_qty > 0.0:
                raw = short_avg * (1.0 - g)
                price = raw - tick * off_buy if post_only else raw
                目标挂单.append(
                    限价挂单(
                        交易对=symbol,
                        方向=订单方向.买,
                        价格=float(price),
                        数量=float(close_qty),
                        只做挂单=post_only,
                        只减仓=True,
                        仓位方向=仓位方向.空,
                    )
                )

        return 策略输出(
            目标挂单=目标挂单,
            备注={
                "symbol": symbol,
                "base_price": float(基准价),
                "grid_percent": float(g),
                "grid_levels": int(levels),
                "last_price": float(最新价),
            },
        )

