# -*- coding: utf-8 -*-
"""
common_core.strategy.models - 策略与执行器共用的数据“语言”

这个文件是干嘛的？
    不同策略、不同执行环境（回测/实盘）之间需要“讲同一种话”。
    这些 dataclass（数据类）就是那套“共同语言”：
    - K线：市场给我们的信息（比如 1 分钟的开高低收）
    - 账户状态：我们手上有什么（余额、持仓、均价）
    - 限价挂单：我们想挂什么单（价格、数量、买/卖）
    - 成交回报：市场把我们的单成交了什么（成交价、成交量）
    - 策略输出：策略一次决策的结果（要挂哪些单、附带哪些说明）

为什么不用一堆 dict？
    dict 像“没有标签的盒子”，你容易把东西放错格子还不报错。
    dataclass 像“有分隔的收纳盒”，字段清晰、类型明确，出错更早暴露。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class 订单方向(str, Enum):
    """
    订单方向

    - 买：买入（BUY）
    - 卖：卖出（SELL）
    """

    买 = "BUY"
    卖 = "SELL"


class 仓位方向(str, Enum):
    """
    仓位方向（Position Side）

    用在“目标仓位/调仓”类策略里：
    - 多：看涨（LONG）
    - 空：看跌（SHORT）
    - 空仓：不持仓（FLAT）
    """

    多 = "LONG"
    空 = "SHORT"
    空仓 = "FLAT"


@dataclass(frozen=True, slots=True)
class K线:
    """
    1 根 K 线（OHLC：开/高/低/收）

    你可以把它理解成“这一分钟里价格活动的总结”：
    - 开：这一分钟的第一笔成交价
    - 高：这一分钟内最高价
    - 低：这一分钟内最低价
    - 收：这一分钟的最后一笔成交价
    """

    开始时间_ms: int
    收盘时间_ms: int
    开: float
    高: float
    低: float
    收: float
    成交量: float = 0.0


@dataclass(frozen=True, slots=True)
class 账户状态:
    """
    策略决策需要的最小账户状态

    注意：这里是“策略层视角”的状态（简化但够用），不是交易所返回的全量账户信息。
    """

    交易对: str
    账户权益: float
    可用余额: float
    持仓数量: float
    持仓均价: float
    未实现盈亏: float = 0.0


@dataclass(frozen=True, slots=True)
class 限价挂单:
    """
    限价挂单（Limit Order：指定价格挂单）

    字段解释：
    - 只做挂单（post_only）：只允许以“挂单方（Maker）”成交，避免变成“吃单方（Taker）”
    - 只减仓（reduce_only）：只允许减少仓位，避免意外加仓（合约常用）
    """

    交易对: str
    方向: 订单方向
    价格: float
    数量: float
    只做挂单: bool = True
    只减仓: bool = False
    客户端订单ID: str | None = None


@dataclass(frozen=True, slots=True)
class 成交回报:
    """
    成交回报（Trade Fill）

    你可以把它理解成“交易所给你的回执单”：
    - 哪个订单成交了多少
    - 成交价格是多少
    - 成交发生在什么时候
    """

    交易对: str
    成交时间_ms: int
    成交价: float
    成交量: float
    方向: 订单方向
    订单ID: str | None = None
    成交ID: str | None = None
    是否Maker: bool | None = None
    额外信息: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class 目标仓位:
    """
    目标仓位（给“调仓执行器”看的）

    设计思路：
        有些策略并不是“挂很多限价单等成交”，而是更像“每根 K 线收盘决定要不要做多/做空”。
        这种策略更适合输出“目标仓位”，让执行器去决定：
            - 用什么价格成交（bid/ask/收盘价）
            - 成交成本怎么扣（手续费/滑点）
            - 以及最关键的：怎么判定爆仓

    字段解释：
        - 名义杠杆：目标名义 = 账户权益 * 名义杠杆
          类比：你有 100 块押金，杠杆 3 倍，就等价于“借了 200 块”，总共做 300 块的仓位。
    """

    交易对: str
    方向: 仓位方向
    名义杠杆: float = 1.0


@dataclass(frozen=True, slots=True)
class 策略输出:
    """
    策略一次“决策”的输出

    设计原则：
    - 策略只说“我想要什么”（目标挂单列表）
    - 执行器决定“怎么做得最稳”（比如增量改单、撤旧挂新、失败重试等）
    """

    目标挂单: list[限价挂单] = field(default_factory=list)
    目标仓位: 目标仓位 | None = None
    备注: dict[str, Any] = field(default_factory=dict)
