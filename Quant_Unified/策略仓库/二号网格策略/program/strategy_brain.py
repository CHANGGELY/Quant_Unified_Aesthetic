# -*- coding: utf-8 -*-
"""
二号网格策略 - 策略脑子（策略接口版）

这个文件是干嘛的？
    把“2号网格策略”的核心逻辑，包装成 common_core.strategy 的统一接口：
        - 输入：K线收盘价 / 账户状态
        - 输出：要挂哪些限价单（多层挂单）

你可以把它想成：
    - GridStrategy 是“会算网格怎么摆”的大脑
    - 这个文件负责把它翻译成“统一格式的下单意图”（策略输出）

为什么要这么做？
    因为我们想实现“同一份策略脑子，同时喂给：
        - 回测执行器（用 OHLC：开/高/低/收 来撮合）
        - 实盘执行器（发真实订单）
    ”这样回测和实盘才不会越走越歪。

怎么用？
    本文件通常由 `backtest_interface.py` 调用（统一策略接口版回测），你一般不需要直接运行它。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from 基础库.common_core.strategy import K线, 账户状态, 成交回报, 策略输出, 限价挂单, 订单方向
from 策略仓库.二号网格策略.config import Config
from 策略仓库.二号网格策略.program.step2_strategy import GridStrategy


@dataclass(slots=True)
class 二号网格策略回测参数:
    """
    用于回测/实盘共享的最小参数集合

    说明：
        Config 里字段很多，这里只是给“策略脑子包装器”一个更清晰的视图。
        仍然支持直接传 Config。
    """

    symbol: str
    money: float
    direction_mode: str = "neutral"  # neutral/long/short
    orders_per_side: int = 1
    post_only: bool = True
    post_only_tick_offset_buy: int = 1
    post_only_tick_offset_sell: int = 1
    tick_size: float = 0.01


class 二号网格策略脑子:
    """
    2号网格策略脑子（统一策略接口版）
    """

    策略名称 = "2号网格策略"

    def __init__(self, 配置: Config | dict) -> None:
        # 统一为 dict，方便补默认字段
        if isinstance(配置, Config):
            cfg = 配置.to_dict()
            # 一些 Config 里没放进 to_dict 的字段，在这里兜底（存在就补进去）
            for k in (
                "orders_per_side",
                "direction_mode",
                "post_only",
                "post_only_tick_offset_buy",
                "post_only_tick_offset_sell",
                "tick_size",
            ):
                if k not in cfg and hasattr(配置, k):
                    cfg[k] = getattr(配置, k)
            self._初始资金 = float(getattr(配置, "money", 0.0) or 0.0)
        else:
            cfg = dict(配置)
            self._初始资金 = float(cfg.get("money", 0.0) or 0.0)

        # 关键：把 GridStrategy 切到“实盘口径”
        # - is_live=True：update_price 触发的 update_order 不会修改持仓（避免“脑子自己撮合”）
        # - external_risk_control=True：爆仓由外部执行器统一判定
        cfg["is_live"] = True
        cfg["external_risk_control"] = True

        self._引擎 = GridStrategy(cfg)
        self._已初始化 = False

    # =========================
    # 统一接口
    # =========================

    def 在K线收盘(self, k线: K线, 账户: 账户状态) -> 策略输出:
        self._同步账户到内部引擎(账户)

        ts = datetime.fromtimestamp(int(k线.收盘时间_ms) / 1000.0)
        最新价 = float(k线.收)

        # 第一次用收盘价初始化网格参数
        if not self._已初始化:
            self._引擎.update_price(ts, 最新价)
            self._已初始化 = True
        else:
            # 实盘是 tick 驱动；回测这里用 1m 收盘来近似（干净且足够稳）
            self._引擎.update_price(ts, 最新价)

        return self._生成策略输出(最新价=最新价, 账户=账户)

    def 在价格更新(self, 时间_ms: int, 最新价: float, 账户: 账户状态) -> 策略输出 | None:
        """
        可选：如果你未来希望更贴近实盘（秒级/逐笔），就用它。

        回测目前默认只用 1m 收盘驱动，避免“过度拟合到分钟内路径假设”。
        """
        if not self._已初始化:
            # 未初始化时，交给 在K线收盘 去做第一次初始化
            return None

        self._同步账户到内部引擎(账户)
        ts = datetime.fromtimestamp(int(时间_ms) / 1000.0)
        self._引擎.update_price(ts, float(最新价))
        return self._生成策略输出(最新价=float(最新价), 账户=账户)

    def 在成交回报(self, 回报: 成交回报) -> None:
        # 先确保初始化过（否则内部状态可能没有网格参数）
        if not self._已初始化:
            return

        ts = datetime.fromtimestamp(int(回报.成交时间_ms) / 1000.0)
        side = str(回报.方向.value)
        self._引擎.curr_price = float(回报.成交价)
        self._引擎.update_order(ts, float(回报.成交价), side, actual_qty=float(回报.成交量))

    # =========================
    # 内部工具
    # =========================

    def _同步账户到内部引擎(self, 账户: 账户状态) -> None:
        """
        让 GridStrategy 的“内部状态”跟外部账户保持一致。

        为什么要同步？
            - GridStrategy 里有复利模式：它需要知道“当前总权益”来放大下单量
            - 但在统一架构里，账户权益由执行器维护，所以这里要以执行器为准
        """
        pos_qty = float(账户.持仓数量)
        avg_price = float(账户.持仓均价)
        unreal = float(账户.未实现盈亏)

        # 账户权益 = 初始资金 + 已实现 + 未实现 => 已实现 = 权益 - 初始 - 未实现
        realized = float(账户.账户权益 - self._初始资金 - unreal)

        self._引擎.money = float(self._初始资金)
        self._引擎.account_dict["positions_qty"] = pos_qty
        self._引擎.account_dict["avg_price"] = avg_price
        self._引擎.account_dict["pair_profit"] = realized

    def _生成策略输出(self, *, 最新价: float, 账户: 账户状态) -> 策略输出:
        conf = self._引擎.config

        交易对 = str(getattr(账户, "交易对", "") or conf.get("symbol", "") or "UNKNOWN").upper()
        direction = str(conf.get("direction_mode", "neutral") or "neutral").lower()
        orders_per_side = int(conf.get("orders_per_side", 1) or 1)
        orders_per_side = max(1, orders_per_side)

        interval = float(self._引擎.grid_dict.get("interval", 0.0) or 0.0)
        mode_val = getattr(getattr(self._引擎, "interval_mode", None), "value", None)
        use_gs = bool(mode_val == "geometric_sequence")

        post_only_flag = bool(conf.get("post_only", True))
        tick_size = float(conf.get("tick_size", 0.01) or 0.01)
        offset_buy = int(conf.get("post_only_tick_offset_buy", 1) or 1)
        offset_sell = int(conf.get("post_only_tick_offset_sell", 1) or 1)

        down_price = float(self._引擎.account_dict.get("down_price", 0.0) or 0.0)
        up_price = float(self._引擎.account_dict.get("up_price", 0.0) or 0.0)

        pos_qty = float(账户.持仓数量)

        # ====== 需要挂哪些方向的单？（对齐实盘 update_expected_orders）======
        need_buy = down_price > 0.0
        need_sell = up_price > 0.0

        if direction == "short" and abs(pos_qty) <= 0.0:
            need_buy = False
        if direction == "long" and abs(pos_qty) <= 0.0:
            need_sell = False

        # ====== 生成多层挂单 ======
        目标挂单: list[限价挂单] = []

        if need_buy:
            base = down_price
            for _ in range(orders_per_side):
                grid_price = float(base)
                if grid_price <= 0:
                    break

                try:
                    qty = float(self._引擎.get_current_trade_qty(grid_price))
                except Exception:
                    qty = 0.0

                # short 模式下 BUY 是回补（只减仓）
                reduce_only = False
                if direction == "short":
                    reduce_only = True
                    if abs(pos_qty) > 0:
                        qty = min(qty, abs(pos_qty))
                    else:
                        qty = 0.0

                if qty > 0:
                    price_new = grid_price - tick_size * offset_buy if post_only_flag else grid_price
                    if price_new > 0:
                        目标挂单.append(
                            限价挂单(
                                交易对=交易对,
                                方向=订单方向.买,
                                价格=float(price_new),
                                数量=float(qty),
                                只做挂单=bool(post_only_flag),
                                只减仓=bool(reduce_only),
                            )
                        )

                if use_gs and interval > 0:
                    base = base / (1.0 + interval)
                else:
                    base = base - interval

        if need_sell:
            base = up_price
            for _ in range(orders_per_side):
                grid_price = float(base)
                if grid_price <= 0:
                    break

                try:
                    qty = float(self._引擎.get_current_trade_qty(grid_price))
                except Exception:
                    qty = 0.0

                # long 模式下 SELL 是止盈（只减仓）
                reduce_only = False
                if direction == "long":
                    reduce_only = True
                    if abs(pos_qty) > 0:
                        qty = min(qty, abs(pos_qty))
                    else:
                        qty = 0.0

                if qty > 0:
                    price_new = grid_price + tick_size * offset_sell if post_only_flag else grid_price
                    if price_new > 0:
                        目标挂单.append(
                            限价挂单(
                                交易对=交易对,
                                方向=订单方向.卖,
                                价格=float(price_new),
                                数量=float(qty),
                                只做挂单=bool(post_only_flag),
                                只减仓=bool(reduce_only),
                            )
                        )

                if use_gs and interval > 0:
                    base = base * (1.0 + interval)
                else:
                    base = base + interval

        return 策略输出(
            目标挂单=目标挂单,
            备注={
                "symbol": 交易对,
                "direction_mode": direction,
                "orders_per_side": orders_per_side,
                "interval": interval,
                "interval_mode": mode_val or "unknown",
                "down_price": down_price,
                "up_price": up_price,
                "last_price": float(最新价),
            },
        )
