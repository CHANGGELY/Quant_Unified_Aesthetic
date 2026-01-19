# -*- coding: utf-8 -*-
"""
九号布林策略 - 策略脑子（只负责“生成信号”，不负责下单）

这个文件是干嘛的？
    你可以把它当成“报警器的大脑”：
    - 输入：每分钟一根 1m K线（开高低收）
    - 内部：把 1m 聚合成 5m/15m/30m/1h/4h（对齐交易所标准周期）
            然后按你指定的口径 A：每分钟都更新一次布林带与均线
    - 输出：满足规则时，返回“下一分钟要推送的信号”（用于钉钉推送）

为什么一定要“每分钟算一次”？
    你举的例子里，12:02 这一分钟就要判断“当前 5m 桶里最高价有没有上穿布林上轨”，
    然后 12:03 才推送信号。
    所以我们不能等 5m/15m 真正收盘才算 —— 必须每分钟都能用“当前桶的实时高/低/收”算一次。

术语解释（遇到英文缩写必须展开）：
    - MA（Moving Average）：移动平均线，例如 MA5=最近 5 根收盘价的平均
    - Bollinger Bands（布林带/布林线）：中轨=均值；标准差≈“波动有多抖”；上下轨=中轨±K*标准差
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Iterable


@dataclass(frozen=True, slots=True)
class 分钟K线:
    开始时间_ms: int
    结束时间_ms: int
    开: float
    高: float
    低: float
    收: float
    量: float = 0.0


@dataclass(frozen=True, slots=True)
class 周期K线:
    """
    周期K线快照（可能是“运行中”的，也可能是“刚收盘”的）

    注意：
        - 桶起点/桶终点对齐交易所周期（例如 5m：12:00~12:05）
        - 我们每分钟都输出一个快照：用于“每分钟算一次”的实时判断
    """

    周期分钟: int
    桶起点_ms: int
    桶终点_ms: int
    开: float
    高: float
    低: float
    收: float
    量: float = 0.0


@dataclass(frozen=True, slots=True)
class 待推送信号:
    推送时间_ms: int
    文本: str
    去重键: str


def _均值(xs: Iterable[float]) -> float:
    xs = list(xs)
    if not xs:
        return float("nan")
    return float(sum(xs) / float(len(xs)))


def _均值与标准差(xs: list[float]) -> tuple[float, float]:
    """
    总体标准差（ddof=0）：布林带常用口径

    用“E[x^2] - (E[x])^2”的方式算，更省算力：
        - E[x]   = 平均值
        - E[x^2] = 平方的平均值
        - 方差   = E[x^2] - (E[x])^2
    """
    n = len(xs)
    if n <= 0:
        return float("nan"), float("nan")
    s = float(sum(xs))
    sq = float(sum(x * x for x in xs))
    mean = s / float(n)
    var = max(sq / float(n) - mean * mean, 0.0)
    return float(mean), float(math.sqrt(var))


def _格式化时间(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _分钟数(ms: int) -> int:
    return int(ms // 60_000)


def _桶起点_ms(*, 开始时间_ms: int, 周期分钟: int) -> int:
    周期_ms = int(周期分钟) * 60_000
    return (int(开始时间_ms) // 周期_ms) * 周期_ms


class _周期聚合器:
    """
    把 1m K线聚合成 T 分钟的“当前桶快照”。

    关键点：
        1) 分桶对齐交易所标准周期（不是滚动 5 分钟）
        2) 每分钟都能拿到“当前桶”的高/低/收（用于实时判断）
        3) 收盘时把收盘价写入历史序列（用于布林/均线）
    """

    def __init__(self, *, 周期分钟: int, 历史收盘上限: int = 2048) -> None:
        self.周期分钟 = int(周期分钟)
        if self.周期分钟 <= 0:
            raise ValueError("周期分钟 必须 > 0")
        self._周期_ms = int(self.周期分钟 * 60_000)

        self._当前桶起点_ms: int | None = None
        self._当前桶终点_ms: int | None = None
        self._开: float = 0.0
        self._高: float = 0.0
        self._低: float = 0.0
        self._收: float = 0.0
        self._量: float = 0.0

        self._已收盘收盘价: Deque[float] = deque(maxlen=int(max(64, 历史收盘上限)))

    def 历史收盘价(self) -> list[float]:
        return list(self._已收盘收盘价)

    def 更新并取快照(self, k: 分钟K线) -> tuple[周期K线, bool]:
        """
        输入一根 1m K线，返回：
            (周期K线快照, 本次是否刚好收盘)

        解释：
            - “是否刚好收盘”= 本分钟结束时间 >= 桶终点
            - 即使刚好收盘，我们也会先返回“收盘那根的快照”，再把它写入历史并清空桶状态
        """
        start_ms = int(k.开始时间_ms)
        end_ms = int(k.结束时间_ms)
        if end_ms <= start_ms:
            raise ValueError("分钟K线时间非法：结束时间_ms 必须 > 开始时间_ms")

        bucket_start = _桶起点_ms(开始时间_ms=start_ms, 周期分钟=self.周期分钟)
        bucket_end = int(bucket_start + self._周期_ms)

        # 进入新桶：先把旧桶落到历史，再开新桶
        if self._当前桶起点_ms is None or bucket_start != self._当前桶起点_ms:
            if self._当前桶起点_ms is not None:
                self._已收盘收盘价.append(float(self._收))

            self._当前桶起点_ms = int(bucket_start)
            self._当前桶终点_ms = int(bucket_end)
            self._开 = float(k.开)
            self._高 = float(k.高)
            self._低 = float(k.低)
            self._收 = float(k.收)
            self._量 = float(k.量)
        else:
            # 同桶内更新
            self._高 = max(float(self._高), float(k.高))
            self._低 = min(float(self._低), float(k.低)) if self._低 > 0 else float(k.低)
            self._收 = float(k.收)
            self._量 += float(k.量)

        snap = 周期K线(
            周期分钟=int(self.周期分钟),
            桶起点_ms=int(self._当前桶起点_ms),
            桶终点_ms=int(self._当前桶终点_ms or bucket_end),
            开=float(self._开),
            高=float(self._高),
            低=float(self._低),
            收=float(self._收),
            量=float(self._量),
        )

        已收盘 = bool(end_ms >= int(self._当前桶终点_ms or bucket_end))
        if 已收盘:
            self._已收盘收盘价.append(float(self._收))
            self._当前桶起点_ms = None
            self._当前桶终点_ms = None
            self._开 = self._高 = self._低 = self._收 = self._量 = 0.0

        return snap, 已收盘


class 九号布林策略脑子:
    """
    九号策略脑子（纯决策）

    输入：每分钟一根 1m K线
    输出：可能产生 0~N 条“下一分钟要推送的信号”
    """

    def __init__(
        self,
        *,
        交易对: str,
        布林窗口: int,
        布林倍数: float,
        回看根数: int,
        阈值_15m_ma收敛: float,
        阈值_30m_ma收敛: float,
        阈值_1h_ma收敛_上穿: float,
        阈值_1h_ma收敛_下穿: float,
        阈值_4h_ma收敛: float,
        阈值_1d_ma收敛: float,
    ) -> None:
        self.交易对 = str(交易对).upper().strip()
        if not self.交易对:
            raise ValueError("交易对不能为空")

        self._布林窗口 = int(布林窗口)
        self._布林倍数 = float(布林倍数)
        if self._布林窗口 <= 2:
            raise ValueError("布林窗口 必须 > 2（因为要用到前2/前1/当前标准差）")
        if self._布林倍数 <= 0:
            raise ValueError("布林倍数 必须 > 0")

        self._回看根数 = int(max(1, 回看根数))

        # ====== 门槛阈值（你给的数字）======
        self._阈值_15m = float(阈值_15m_ma收敛)
        self._阈值_30m = float(阈值_30m_ma收敛)
        self._阈值_1h_up = float(阈值_1h_ma收敛_上穿)
        self._阈值_1h_dn = float(阈值_1h_ma收敛_下穿)
        self._阈值_4h = float(阈值_4h_ma收敛)
        self._阈值_1d = float(阈值_1d_ma收敛)

        # ====== 1m -> 多周期聚合器（对齐交易所周期）======
        self._agg_5m = _周期聚合器(周期分钟=5)
        self._agg_15m = _周期聚合器(周期分钟=15)
        self._agg_30m = _周期聚合器(周期分钟=30)
        self._agg_1h = _周期聚合器(周期分钟=60)
        self._agg_4h = _周期聚合器(周期分钟=240)

        # ====== 各周期布林 std 历史（只要 3 个点，用来判断“口开”形态）======
        self._std_hist_5m: Deque[float] = deque(maxlen=3)
        self._std_hist_15m: Deque[float] = deque(maxlen=3)
        self._std_hist_30m: Deque[float] = deque(maxlen=3)
        self._std_hist_1h: Deque[float] = deque(maxlen=3)
        self._std_hist_4h: Deque[float] = deque(maxlen=3)

        # ====== 门槛：最近 X 分钟内是否出现过“均线收敛” ======
        # 解释：你说“在 5 个 15m 周期之内” -> 用分钟来讲就是 5*15=75 分钟
        self._最近_15m_ma收敛: Deque[bool] = deque(maxlen=self._回看根数 * 15)
        self._最近_30m_ma收敛: Deque[bool] = deque(maxlen=self._回看根数 * 30)
        self._最近_1h_ma收敛_up: Deque[bool] = deque(maxlen=self._回看根数 * 60)
        self._最近_1h_ma收敛_dn: Deque[bool] = deque(maxlen=self._回看根数 * 60)
        self._最近_4h_ma收敛: Deque[bool] = deque(maxlen=self._回看根数 * 240)

        # ====== 日线 MA 收敛（每天更新一次，保存最近 5 天即可）======
        self._daily_close: Deque[float] = deque(maxlen=512)
        self._daily_ma收敛: Deque[bool] = deque(maxlen=self._回看根数)

        # ====== 去重：同一周期桶同向只推一次（避免每分钟刷屏）======
        self._上次触发桶: dict[str, int] = {}

        # WS 乱序保护：只接受严格递增的分钟
        self._上次分钟序号: int | None = None

    # =========================
    # 日线更新：每天一根
    # =========================

    def 喂入一根日线收盘(self, *, 结束时间_ms: int, 收盘价: float) -> None:
        """
        日线只用来计算 MA5/30/60 的收敛门槛（max-min < 2900）
        """
        _ = int(结束时间_ms)
        close = float(收盘价)
        if close <= 0.0:
            return

        self._daily_close.append(close)
        closes = list(self._daily_close)
        if len(closes) < 60:
            self._daily_ma收敛.append(False)
            return

        ma5 = _均值(closes[-5:])
        ma30 = _均值(closes[-30:])
        ma60 = _均值(closes[-60:])
        diff = float(max(ma5, ma30, ma60) - min(ma5, ma30, ma60))
        self._daily_ma收敛.append(bool(diff < self._阈值_1d))

    # =========================
    # 分钟更新：每分钟一根
    # =========================

    def 喂入一分钟K线并产出信号(self, k: 分钟K线) -> list[待推送信号]:
        # Guard Clauses：数据不合法直接挡住（绝不吞错）
        if k.结束时间_ms <= k.开始时间_ms:
            return []
        if k.收 <= 0.0:
            return []

        minute_index = _分钟数(int(k.结束时间_ms))
        if self._上次分钟序号 is not None and minute_index <= self._上次分钟序号:
            # WS 乱序/重复：忽略旧的
            return []
        self._上次分钟序号 = minute_index

        # 1) 更新各周期“运行中 K线”（每分钟都有快照）
        bar_5m, closed_5m = self._agg_5m.更新并取快照(k)
        bar_15m, closed_15m = self._agg_15m.更新并取快照(k)
        bar_30m, closed_30m = self._agg_30m.更新并取快照(k)
        bar_1h, closed_1h = self._agg_1h.更新并取快照(k)
        bar_4h, closed_4h = self._agg_4h.更新并取快照(k)

        closes_5m = self._取用于计算的收盘序列(self._agg_5m, bar_5m, 已收盘=closed_5m)
        closes_15m = self._取用于计算的收盘序列(self._agg_15m, bar_15m, 已收盘=closed_15m)
        closes_30m = self._取用于计算的收盘序列(self._agg_30m, bar_30m, 已收盘=closed_30m)
        closes_1h = self._取用于计算的收盘序列(self._agg_1h, bar_1h, 已收盘=closed_1h)
        closes_4h = self._取用于计算的收盘序列(self._agg_4h, bar_4h, 已收盘=closed_4h)

        # 2) 先更新“均线收敛门槛”（它是上层触发的条件）
        self._更新均线收敛门槛(
            closes_15m=closes_15m,
            closes_30m=closes_30m,
            closes_1h=closes_1h,
            closes_4h=closes_4h,
        )

        # 3) 再计算布林（用于口开 + 上下穿）
        boll_5m = self._计算布林(closes_5m)
        boll_15m = self._计算布林(closes_15m)
        boll_30m = self._计算布林(closes_30m)
        boll_1h = self._计算布林(closes_1h)
        boll_4h = self._计算布林(closes_4h)

        if boll_5m is not None:
            self._std_hist_5m.append(float(boll_5m["std"]))
        if boll_15m is not None:
            self._std_hist_15m.append(float(boll_15m["std"]))
        if boll_30m is not None:
            self._std_hist_30m.append(float(boll_30m["std"]))
        if boll_1h is not None:
            self._std_hist_1h.append(float(boll_1h["std"]))
        if boll_4h is not None:
            self._std_hist_4h.append(float(boll_4h["std"]))

        # 4) 逐层触发（每分钟都检查一次）
        推送时间 = int(k.结束时间_ms + 60_000)  # 下一分钟
        时刻_ms = int(k.结束时间_ms)

        signals: list[待推送信号] = []

        # ====== 5m ======
        if boll_5m is not None and self._布林口开(self._std_hist_5m) and any(self._最近_15m_ma收敛):
            signals.extend(
                self._生成触发信号(
                    tf_name="5m",
                    bar=bar_5m,
                    boll=boll_5m,
                    推送时间_ms=推送时间,
                    时刻_ms=时刻_ms,
                    门槛文本=f"15分钟均线相差小于{int(self._阈值_15m)}",
                )
            )

        # ====== 15m ======
        if boll_15m is not None and self._布林口开(self._std_hist_15m) and any(self._最近_30m_ma收敛):
            signals.extend(
                self._生成触发信号(
                    tf_name="15m",
                    bar=bar_15m,
                    boll=boll_15m,
                    推送时间_ms=推送时间,
                    时刻_ms=时刻_ms,
                    门槛文本=f"30分钟均线相差小于{int(self._阈值_30m)}",
                )
            )

        # ====== 30m（上下穿门槛不同） ======
        if boll_30m is not None and self._布林口开(self._std_hist_30m):
            signals.extend(
                self._生成触发信号(
                    tf_name="30m",
                    bar=bar_30m,
                    boll=boll_30m,
                    推送时间_ms=推送时间,
                    时刻_ms=时刻_ms,
                    门槛文本=f"1小时均线相差小于{int(self._阈值_1h_up)}",
                    上穿门槛=any(self._最近_1h_ma收敛_up),
                    下穿门槛=any(self._最近_1h_ma收敛_dn),
                    下穿门槛文本=f"1小时均线相差小于{int(self._阈值_1h_dn)}",
                )
            )

        # ====== 1h ======
        if boll_1h is not None and self._布林口开(self._std_hist_1h) and any(self._最近_4h_ma收敛):
            signals.extend(
                self._生成触发信号(
                    tf_name="1h",
                    bar=bar_1h,
                    boll=boll_1h,
                    推送时间_ms=推送时间,
                    时刻_ms=时刻_ms,
                    门槛文本=f"4小时均线相差小于{int(self._阈值_4h)}",
                )
            )

        # ====== 4h（门槛来自日线） ======
        if boll_4h is not None and self._布林口开(self._std_hist_4h) and any(self._daily_ma收敛):
            signals.extend(
                self._生成触发信号(
                    tf_name="4h",
                    bar=bar_4h,
                    boll=boll_4h,
                    推送时间_ms=推送时间,
                    时刻_ms=时刻_ms,
                    门槛文本=f"1天均线相差小于{int(self._阈值_1d)}",
                )
            )

        return signals

    # =========================
    # 内部：收盘序列 / 均线 / 布林
    # =========================

    @staticmethod
    def _取用于计算的收盘序列(agg: _周期聚合器, bar: 周期K线, *, 已收盘: bool) -> list[float]:
        """
        统一口径：
            - 若本周期“刚好收盘”，bar.收 已经被写进历史收盘价了 -> 直接用历史即可
            - 若仍在运行中，bar.收 还没进历史 -> 历史 + 当前收盘（每分钟更新）
        """
        closes = agg.历史收盘价()
        if 已收盘:
            return closes
        return closes + [float(bar.收)]

    @staticmethod
    def _计算_ma_diff(closes: list[float]) -> float | None:
        if len(closes) < 60:
            return None
        ma5 = _均值(closes[-5:])
        ma30 = _均值(closes[-30:])
        ma60 = _均值(closes[-60:])
        return float(max(ma5, ma30, ma60) - min(ma5, ma30, ma60))

    def _更新均线收敛门槛(
        self,
        *,
        closes_15m: list[float],
        closes_30m: list[float],
        closes_1h: list[float],
        closes_4h: list[float],
    ) -> None:
        d15 = self._计算_ma_diff(closes_15m)
        self._最近_15m_ma收敛.append(bool(d15 is not None and d15 < self._阈值_15m))

        d30 = self._计算_ma_diff(closes_30m)
        self._最近_30m_ma收敛.append(bool(d30 is not None and d30 < self._阈值_30m))

        d60 = self._计算_ma_diff(closes_1h)
        self._最近_1h_ma收敛_up.append(bool(d60 is not None and d60 < self._阈值_1h_up))
        self._最近_1h_ma收敛_dn.append(bool(d60 is not None and d60 < self._阈值_1h_dn))

        d240 = self._计算_ma_diff(closes_4h)
        self._最近_4h_ma收敛.append(bool(d240 is not None and d240 < self._阈值_4h))

    def _计算布林(self, closes: list[float]) -> dict[str, float] | None:
        if len(closes) < self._布林窗口:
            return None
        window = list(closes[-self._布林窗口 :])
        mid, std = _均值与标准差(window)
        up = float(mid + self._布林倍数 * std)
        dn = float(mid - self._布林倍数 * std)
        return {"mid": float(mid), "std": float(std), "up": up, "dn": dn}

    @staticmethod
    def _布林口开(std_hist: Deque[float]) -> bool:
        if len(std_hist) < 3:
            return False
        a, b, c = list(std_hist)[-3:]
        return bool(float(a) > float(b) and float(b) < float(c))

    def _生成触发信号(
        self,
        *,
        tf_name: str,
        bar: 周期K线,
        boll: dict[str, float],
        推送时间_ms: int,
        时刻_ms: int,
        门槛文本: str,
        上穿门槛: bool | None = None,
        下穿门槛: bool | None = None,
        下穿门槛文本: str | None = None,
    ) -> list[待推送信号]:
        """
        生成“上穿/下穿”的信号文本（按你给的固定话术）

        去重规则（非常重要，避免刷屏）：
            - 同一周期桶（bar.桶起点_ms）同一个方向，只推一次
        """
        if boll["up"] <= 0.0 or boll["dn"] <= 0.0:
            return []

        up = float(boll["up"])
        dn = float(boll["dn"])
        signals: list[待推送信号] = []

        def _去重通过(方向: str) -> bool:
            key = f"{tf_name}_{方向}"
            last_bucket = self._上次触发桶.get(key)
            if last_bucket == int(bar.桶起点_ms):
                return False
            self._上次触发桶[key] = int(bar.桶起点_ms)
            return True

        # 上穿
        if float(bar.高) > up:
            if 上穿门槛 is None:
                上穿门槛 = True
            if 上穿门槛 and _去重通过("up"):
                文案 = (
                    f"布林 九号策略信号：{门槛文本}，前一周期上穿布林轨。\n"
                    f"交易对: {self.交易对}\n"
                    f"触发周期: {tf_name}\n"
                    f"触发时间: {_格式化时间(int(时刻_ms))}"
                )
                signals.append(
                    待推送信号(
                        推送时间_ms=int(推送时间_ms),
                        文本=文案,
                        去重键=f"{tf_name}_up@{int(bar.桶起点_ms)}",
                    )
                )

        # 下穿
        if float(bar.低) < dn:
            if 下穿门槛 is None:
                下穿门槛 = True
            if 下穿门槛 and _去重通过("dn"):
                文案门槛 = 下穿门槛文本 or 门槛文本
                文案 = (
                    f"布林 九号策略信号：{文案门槛}，前一周期下穿布林轨。\n"
                    f"交易对: {self.交易对}\n"
                    f"触发周期: {tf_name}\n"
                    f"触发时间: {_格式化时间(int(时刻_ms))}"
                )
                signals.append(
                    待推送信号(
                        推送时间_ms=int(推送时间_ms),
                        文本=文案,
                        去重键=f"{tf_name}_dn@{int(bar.桶起点_ms)}",
                    )
                )

        return signals

