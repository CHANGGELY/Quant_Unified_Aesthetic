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
from typing import Any, Mapping


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
class 盘口快照:
    """
    L2 盘口快照（Order Book Snapshot：订单簿快照）

    这是什么？
        你可以把“盘口”理解成交易所的“排队队伍”：
        - bid（买盘）：大家挂着“我愿意用多少钱买”
        - ask（卖盘）：大家挂着“我愿意用多少钱卖”
        bid/ask 的最前面，就是“买一/卖一”（最优价格）。

    这个快照用来做什么？
        - 高频策略（例如 5 号预测）会用盘口的形状（量多不多、价差大不大）做特征
        - 高频执行器会用 bid/ask 来模拟“买入要付 ask，卖出拿 bid”的点差成本

    字段约定：
        - bid价/bid量/ask价/ask量 都是从 1 档开始（买一/卖一）
        - 缺失档位用 0.0 填充（方便 NumPy/模型喂数据）
    """

    交易对: str
    时间_ms: int
    bid价: tuple[float, ...]
    bid量: tuple[float, ...]
    ask价: tuple[float, ...]
    ask量: tuple[float, ...]

    @property
    def 深度档数(self) -> int:
        return int(min(len(self.bid价), len(self.ask价)))

    def 买一价(self) -> float:
        return float(self.bid价[0]) if self.bid价 else 0.0

    def 卖一价(self) -> float:
        return float(self.ask价[0]) if self.ask价 else 0.0

    def 计算中间价(self) -> float:
        bid1 = float(self.买一价())
        ask1 = float(self.卖一价())
        if bid1 > 0.0 and ask1 > 0.0:
            return float((bid1 + ask1) * 0.5)
        return float(max(bid1, ask1, 0.0))

    def 计算加权中间价(self) -> float:
        """
        加权中间价（Weighted Mid Price）

        用人话说：
            - 如果买一量更大，价格更“偏向买方”
            - 如果卖一量更大，价格更“偏向卖方”
        """
        bid1 = float(self.买一价())
        ask1 = float(self.卖一价())
        if bid1 <= 0.0 or ask1 <= 0.0:
            return float(max(bid1, ask1, 0.0))

        bq1 = float(self.bid量[0]) if self.bid量 else 0.0
        aq1 = float(self.ask量[0]) if self.ask量 else 0.0
        denom = bq1 + aq1
        if denom <= 0.0:
            return float((bid1 + ask1) * 0.5)

        return float((bid1 * aq1 + ask1 * bq1) / denom)

    @classmethod
    def 从扁平字典(
        cls,
        *,
        交易对: str,
        时间_ms: int,
        depth_levels: int,
        数据: Mapping[str, Any],
    ) -> "盘口快照":
        if depth_levels <= 0:
            raise ValueError("depth_levels 必须 > 0")
        bid价 = tuple(float(数据.get(f"bid{i}_p", 0.0) or 0.0) for i in range(1, depth_levels + 1))
        bid量 = tuple(float(数据.get(f"bid{i}_q", 0.0) or 0.0) for i in range(1, depth_levels + 1))
        ask价 = tuple(float(数据.get(f"ask{i}_p", 0.0) or 0.0) for i in range(1, depth_levels + 1))
        ask量 = tuple(float(数据.get(f"ask{i}_q", 0.0) or 0.0) for i in range(1, depth_levels + 1))
        return cls(
            交易对=str(交易对),
            时间_ms=int(时间_ms),
            bid价=bid价,
            bid量=bid量,
            ask价=ask价,
            ask量=ask量,
        )


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
    # ====== 可选扩展：双向持仓（对冲模式）======
    # 解释：
    #   有些合约账户支持“同时持有多头和空头”（对冲模式）。
    #   这时用一个“净持仓数量”是不够的，因为：
    #     - 多头和空头可能同时非 0
    #     - 它们各自的开仓均价也不同
    #
    # 约定：
    #   - 多头持仓数量 / 空头持仓数量 都是“绝对值数量”（>=0）
    #   - 如果你只做单向（净持仓）策略，这些字段保持 0 即可
    多头持仓数量: float = 0.0
    多头持仓均价: float = 0.0
    空头持仓数量: float = 0.0
    空头持仓均价: float = 0.0


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
    # 对冲模式下，需要额外标记“这张单属于多头还是空头”
    # - 多：LONG（多头仓位）
    # - 空：SHORT（空头仓位）
    # - None：表示“净持仓模式/不区分仓位方向”
    仓位方向: 仓位方向 | None = None


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
    仓位方向: 仓位方向 | None = None


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
