# -*- coding: utf-8 -*-
"""
九号布林策略 - 策略脑子（只负责“生成信号”，不负责下单）

这个文件是干嘛的？
    你可以把它当成“判断器”：
    - 输入：每分钟一根 1m K线（开高低收）
    - 内部：把 1m 聚合成 5m/15m/30m/1h/4h，并计算布林线 + MA 均线
    - 输出：满足条件时，返回“下一分钟要推送的信号”（文本）

术语解释（遇到英文缩写要立刻展开）：
    - MA（Moving Average）：移动平均线，MA5/MA30/MA60 就是最近 5/30/60 根收盘价的平均
    - Bollinger Bands（布林带/布林线）：中轨=均线，标准差≈“波动有多抖”，上下轨=中轨±K*标准差
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
    周期分钟: int
    开始时间_ms: int
    结束时间_ms: int
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


def _标准差(xs: list[float]) -> float:
    """
    计算总体标准差（ddof=0），这是布林带更常见的默认口径。
    """
    n = len(xs)
    if n <= 0:
        return float("nan")
    mu = _均值(xs)
    var = sum((x - mu) ** 2 for x in xs) / float(n)
    return float(math.sqrt(max(var, 0.0)))


def _格式化时间(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).astimezone()  # 转为本机时区（通常 UTC+8）
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class _周期聚合器:
    """
    把 1m K线聚合成 T 分钟 K线（对齐交易所标准周期：按 open_time 分桶）
    """

    def __init__(self, 周期分钟: int) -> None:
        self.周期分钟 = int(周期分钟)
        if self.周期分钟 <= 0:
            raise ValueError("周期分钟 必须 > 0")
        self._周期_ms = self.周期分钟 * 60_000

        self._当前桶起点_ms: int | None = None
        self._当前桶终点_ms: int | None = None
        self._开: float = 0.0
        self._高: float = 0.0
        self._低: float = 0.0
        self._收: float = 0.0
        self._量: float = 0.0

    def 喂入(self, k: 分钟K线) -> 周期K线 | None:
        bucket_start = (int(k.开始时间_ms) // self._周期_ms) * self._周期_ms
        bucket_end = int(bucket_start + self._周期_ms)

        # 第一次
        if self._当前桶起点_ms is None:
            self._当前桶起点_ms = bucket_start
            self._当前桶终点_ms = bucket_end
            self._开 = float(k.开)
            self._高 = float(k.高)
            self._低 = float(k.低)
            self._收 = float(k.收)
            self._量 = float(k.量)
            # 1m 周期：这根就收盘
            if int(k.结束时间_ms) >= bucket_end:
                bar = 周期K线(
                    周期分钟=int(self.周期分钟),
                    开始时间_ms=int(self._当前桶起点_ms),
                    结束时间_ms=int(bucket_end),
                    开=float(self._开),
                    高=float(self._高),
                    低=float(self._低),
                    收=float(self._收),
                    量=float(self._量),
                )
                self._当前桶起点_ms = None
                self._当前桶终点_ms = None
                self._开 = self._高 = self._低 = self._收 = self._量 = 0.0
                return bar
            return None

        # 进入新桶：说明上一个桶可能漏了最后一分钟（或数据有跳跃）
        if bucket_start != self._当前桶起点_ms:
            old_start = int(self._当前桶起点_ms)
            old_end = int(self._当前桶终点_ms or (old_start + self._周期_ms))
            bar = 周期K线(
                周期分钟=int(self.周期分钟),
                开始时间_ms=old_start,
                结束时间_ms=old_end,
                开=float(self._开),
                高=float(self._高),
                低=float(self._低),
                收=float(self._收),
                量=float(self._量),
            )

            # 用新桶初始化（并继续处理当前 k）
            self._当前桶起点_ms = bucket_start
            self._当前桶终点_ms = bucket_end
            self._开 = float(k.开)
            self._高 = float(k.高)
            self._低 = float(k.低)
            self._收 = float(k.收)
            self._量 = float(k.量)
            return bar

        # 同一桶内更新
        self._高 = max(float(self._高), float(k.高))
        self._低 = min(float(self._低), float(k.低)) if self._低 > 0 else float(k.低)
        self._收 = float(k.收)
        self._量 += float(k.量)

        # 桶到点：立刻结算（这样“下一分钟推送”才不会晚 1 分钟）
        if int(k.结束时间_ms) >= bucket_end:
            bar = 周期K线(
                周期分钟=int(self.周期分钟),
                开始时间_ms=int(self._当前桶起点_ms),
                结束时间_ms=int(bucket_end),
                开=float(self._开),
                高=float(self._高),
                低=float(self._低),
                收=float(self._收),
                量=float(self._量),
            )
            self._当前桶起点_ms = None
            self._当前桶终点_ms = None
            self._开 = self._高 = self._低 = self._收 = self._量 = 0.0
            return bar

        return None


class _周期指标器:
    """
    对某个周期（例如 5m）维护：
    - 布林带：std、上轨、下轨
    - 均线：MA5/30/60
    """

    def __init__(self, *, 周期分钟: int, 布林窗口: int, 布林倍数: float) -> None:
        self.周期分钟 = int(周期分钟)
        self.布林窗口 = int(布林窗口)
        self.布林倍数 = float(布林倍数)

        if self.周期分钟 <= 0:
            raise ValueError("周期分钟 必须 > 0")
        if self.布林窗口 <= 2:
            raise ValueError("布林窗口 必须 > 2（否则无法做前2/前1/当前比较）")
        if self.布林倍数 <= 0:
            raise ValueError("布林倍数 必须 > 0")

        # 为了算 MA60、以及布林 std(t-2,t-1,t)，我们需要保留足够长的历史
        self._bars: Deque[周期K线] = deque(maxlen=512)
        self._close: Deque[float] = deque(maxlen=512)

        self._boll_std: Deque[float | None] = deque(maxlen=512)
        self._boll_up: Deque[float | None] = deque(maxlen=512)
        self._boll_dn: Deque[float | None] = deque(maxlen=512)

        self._ma5: Deque[float | None] = deque(maxlen=512)
        self._ma30: Deque[float | None] = deque(maxlen=512)
        self._ma60: Deque[float | None] = deque(maxlen=512)
        self._ma_diff: Deque[float | None] = deque(maxlen=512)  # max(MA*)-min(MA*)

    def 最新K线(self) -> 周期K线 | None:
        return self._bars[-1] if self._bars else None

    def 最新布林std(self) -> float | None:
        return self._boll_std[-1] if self._boll_std else None

    def 最新布林上轨(self) -> float | None:
        return self._boll_up[-1] if self._boll_up else None

    def 最新布林下轨(self) -> float | None:
        return self._boll_dn[-1] if self._boll_dn else None

    def 最新_ma_diff(self) -> float | None:
        return self._ma_diff[-1] if self._ma_diff else None

    def 最近N根_ma_diff(self, n: int) -> list[float]:
        n = int(max(1, n))
        vals: list[float] = []
        for v in list(self._ma_diff)[-n:]:
            if v is None:
                continue
            vals.append(float(v))
        return vals

    def 最近N根_布林std(self, n: int) -> list[float]:
        n = int(max(1, n))
        vals: list[float] = []
        for v in list(self._boll_std)[-n:]:
            if v is None:
                continue
            vals.append(float(v))
        return vals

    def 追加K线并计算(self, bar: 周期K线) -> None:
        self._bars.append(bar)
        self._close.append(float(bar.收))

        closes = list(self._close)

        # ====== 布林 ======
        if len(closes) >= self.布林窗口:
            window = closes[-self.布林窗口 :]
            mid = _均值(window)
            std = _标准差(window)
            up = mid + self.布林倍数 * std
            dn = mid - self.布林倍数 * std
            self._boll_std.append(float(std))
            self._boll_up.append(float(up))
            self._boll_dn.append(float(dn))
        else:
            self._boll_std.append(None)
            self._boll_up.append(None)
            self._boll_dn.append(None)

        # ====== MA ======
        self._ma5.append(_均值(closes[-5:]) if len(closes) >= 5 else None)
        self._ma30.append(_均值(closes[-30:]) if len(closes) >= 30 else None)
        self._ma60.append(_均值(closes[-60:]) if len(closes) >= 60 else None)

        ma5 = self._ma5[-1]
        ma30 = self._ma30[-1]
        ma60 = self._ma60[-1]
        if ma5 is None or ma30 is None or ma60 is None:
            self._ma_diff.append(None)
        else:
            mx = max(float(ma5), float(ma30), float(ma60))
            mn = min(float(ma5), float(ma30), float(ma60))
            self._ma_diff.append(float(mx - mn))

    def 布林口开(self) -> bool:
        """
        口开判定（按你的规则）：
            std[t-2] > std[t-1] 且 std[t-1] < std[t]
        """
        if len(self._boll_std) < 3:
            return False
        a, b, c = list(self._boll_std)[-3:]
        if a is None or b is None or c is None:
            return False
        return bool(float(a) > float(b) and float(b) < float(c))


class 九号布林策略脑子:
    """
    只负责输出“待推送信号”
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
        self._回看根数 = int(max(1, 回看根数))

        self._阈值_15m = float(阈值_15m_ma收敛)
        self._阈值_30m = float(阈值_30m_ma收敛)
        self._阈值_1h_up = float(阈值_1h_ma收敛_上穿)
        self._阈值_1h_dn = float(阈值_1h_ma收敛_下穿)
        self._阈值_4h = float(阈值_4h_ma收敛)
        self._阈值_1d = float(阈值_1d_ma收敛)

        # ====== 1m -> 多周期聚合器 ======
        self._agg_5m = _周期聚合器(5)
        self._agg_15m = _周期聚合器(15)
        self._agg_30m = _周期聚合器(30)
        self._agg_1h = _周期聚合器(60)
        self._agg_4h = _周期聚合器(240)

        # ====== 多周期指标器 ======
        self._ind_5m = _周期指标器(周期分钟=5, 布林窗口=布林窗口, 布林倍数=布林倍数)
        self._ind_15m = _周期指标器(周期分钟=15, 布林窗口=布林窗口, 布林倍数=布林倍数)
        self._ind_30m = _周期指标器(周期分钟=30, 布林窗口=布林窗口, 布林倍数=布林倍数)
        self._ind_1h = _周期指标器(周期分钟=60, 布林窗口=布林窗口, 布林倍数=布林倍数)
        self._ind_4h = _周期指标器(周期分钟=240, 布林窗口=布林窗口, 布林倍数=布林倍数)

        # 日线只用于“MA 收敛门槛”，不做 1m 聚合（用外部喂入日线收盘）
        self._daily_close: Deque[float] = deque(maxlen=512)
        self._daily_ma_diff: Deque[float | None] = deque(maxlen=512)
        self._daily_bar_end_ms: Deque[int] = deque(maxlen=512)

    # =========================
    # 日线喂入（来自 REST/WS 的 1d K线）
    # =========================

    def 喂入一根日线收盘(self, *, 结束时间_ms: int, 收盘价: float) -> None:
        self._daily_bar_end_ms.append(int(结束时间_ms))
        self._daily_close.append(float(收盘价))
        closes = list(self._daily_close)
        if len(closes) >= 60:
            ma5 = _均值(closes[-5:])
            ma30 = _均值(closes[-30:])
            ma60 = _均值(closes[-60:])
            mx = max(ma5, ma30, ma60)
            mn = min(ma5, ma30, ma60)
            self._daily_ma_diff.append(float(mx - mn))
        else:
            self._daily_ma_diff.append(None)

    def _最近N根日线_ma_diff(self, n: int) -> list[float]:
        n = int(max(1, n))
        vals: list[float] = []
        for v in list(self._daily_ma_diff)[-n:]:
            if v is None:
                continue
            vals.append(float(v))
        return vals

    # =========================
    # 1m 喂入（主入口）
    # =========================

    def 喂入一分钟K线(self, k: 分钟K线) -> list[tuple[str, 周期K线]]:
        """
        返回“刚刚收盘的多周期 K线列表”，格式：(周期名, 周期K线)
        """
        closed: list[tuple[str, 周期K线]] = []

        bar_4h = self._agg_4h.喂入(k)
        if bar_4h:
            closed.append(("4h", bar_4h))

        bar_1h = self._agg_1h.喂入(k)
        if bar_1h:
            closed.append(("1h", bar_1h))

        bar_30m = self._agg_30m.喂入(k)
        if bar_30m:
            closed.append(("30m", bar_30m))

        bar_15m = self._agg_15m.喂入(k)
        if bar_15m:
            closed.append(("15m", bar_15m))

        bar_5m = self._agg_5m.喂入(k)
        if bar_5m:
            closed.append(("5m", bar_5m))

        return closed

    def 处理已收盘周期K线并产出信号(self, closed_bars: list[tuple[str, 周期K线]]) -> list[待推送信号]:
        """
        输入：本分钟内刚刚收盘的各周期K线（可能多条）
        输出：需要在“下一分钟”推送的信号列表
        """
        if not closed_bars:
            return []

        # 先按“从大到小”处理，确保门槛周期先更新
        优先级 = {"4h": 240, "1h": 60, "30m": 30, "15m": 15, "5m": 5}
        closed_bars = sorted(closed_bars, key=lambda x: 优先级.get(x[0], 0), reverse=True)

        signals: list[待推送信号] = []

        for tf, bar in closed_bars:
            if tf == "4h":
                self._ind_4h.追加K线并计算(bar)
                signals.extend(self._检查触发_4h(bar))
            elif tf == "1h":
                self._ind_1h.追加K线并计算(bar)
                signals.extend(self._检查触发_1h(bar))
            elif tf == "30m":
                self._ind_30m.追加K线并计算(bar)
                signals.extend(self._检查触发_30m(bar))
            elif tf == "15m":
                self._ind_15m.追加K线并计算(bar)
                signals.extend(self._检查触发_15m(bar))
            elif tf == "5m":
                self._ind_5m.追加K线并计算(bar)
                signals.extend(self._检查触发_5m(bar))

        return signals

    # =========================
    # 触发逻辑（按你给的规则逐层写死）
    # =========================

    def _是否满足_ma收敛_最近N根(self, 指标器: _周期指标器, *, n: int, threshold: float) -> bool:
        diffs = 指标器.最近N根_ma_diff(n)
        return bool(diffs and any(d < float(threshold) for d in diffs))

    def _检查触发_5m(self, bar: 周期K线) -> list[待推送信号]:
        if not self._ind_5m.布林口开():
            return []
        up = self._ind_5m.最新布林上轨()
        dn = self._ind_5m.最新布林下轨()
        if up is None or dn is None:
            return []

        有15m收敛 = self._是否满足_ma收敛_最近N根(self._ind_15m, n=self._回看根数, threshold=self._阈值_15m)
        if not 有15m收敛:
            return []

        signals: list[待推送信号] = []
        推送时间 = int(bar.结束时间_ms + 60_000)  # 下一分钟

        if float(bar.高) > float(up):
            文案 = (
                f"布林 九号策略信号：15分钟均线相差小于{int(self._阈值_15m)}，前一周期上穿布林轨。\n"
                f"交易对: {self.交易对}\n"
                f"触发周期: 5m\n"
                f"触发时间: {_格式化时间(bar.结束时间_ms)}"
            )
            signals.append(待推送信号(推送时间_ms=推送时间, 文本=文案, 去重键=f"5m_up@{bar.结束时间_ms}"))

        if float(bar.低) < float(dn):
            文案 = (
                f"布林 九号策略信号：15分钟均线相差小于{int(self._阈值_15m)}，前一周期下穿布林轨。\n"
                f"交易对: {self.交易对}\n"
                f"触发周期: 5m\n"
                f"触发时间: {_格式化时间(bar.结束时间_ms)}"
            )
            signals.append(待推送信号(推送时间_ms=推送时间, 文本=文案, 去重键=f"5m_dn@{bar.结束时间_ms}"))

        return signals

    def _检查触发_15m(self, bar: 周期K线) -> list[待推送信号]:
        if not self._ind_15m.布林口开():
            return []
        up = self._ind_15m.最新布林上轨()
        dn = self._ind_15m.最新布林下轨()
        if up is None or dn is None:
            return []

        有30m收敛 = self._是否满足_ma收敛_最近N根(self._ind_30m, n=self._回看根数, threshold=self._阈值_30m)
        if not 有30m收敛:
            return []

        signals: list[待推送信号] = []
        推送时间 = int(bar.结束时间_ms + 60_000)

        if float(bar.高) > float(up):
            文案 = (
                f"布林 九号策略信号：30分钟均线相差小于{int(self._阈值_30m)}，前一周期上穿布林轨。\n"
                f"交易对: {self.交易对}\n"
                f"触发周期: 15m\n"
                f"触发时间: {_格式化时间(bar.结束时间_ms)}"
            )
            signals.append(待推送信号(推送时间_ms=推送时间, 文本=文案, 去重键=f"15m_up@{bar.结束时间_ms}"))

        if float(bar.低) < float(dn):
            文案 = (
                f"布林 九号策略信号：30分钟均线相差小于{int(self._阈值_30m)}，前一周期下穿布林轨。\n"
                f"交易对: {self.交易对}\n"
                f"触发周期: 15m\n"
                f"触发时间: {_格式化时间(bar.结束时间_ms)}"
            )
            signals.append(待推送信号(推送时间_ms=推送时间, 文本=文案, 去重键=f"15m_dn@{bar.结束时间_ms}"))

        return signals

    def _检查触发_30m(self, bar: 周期K线) -> list[待推送信号]:
        if not self._ind_30m.布林口开():
            return []
        up = self._ind_30m.最新布林上轨()
        dn = self._ind_30m.最新布林下轨()
        if up is None or dn is None:
            return []

        signals: list[待推送信号] = []
        推送时间 = int(bar.结束时间_ms + 60_000)

        # 上穿：1h 收敛阈值=1800
        if float(bar.高) > float(up):
            有1h收敛 = self._是否满足_ma收敛_最近N根(self._ind_1h, n=self._回看根数, threshold=self._阈值_1h_up)
            if 有1h收敛:
                文案 = (
                    f"布林 九号策略信号：1小时均线相差小于{int(self._阈值_1h_up)}，前一周期上穿布林轨。\n"
                    f"交易对: {self.交易对}\n"
                    f"触发周期: 30m\n"
                    f"触发时间: {_格式化时间(bar.结束时间_ms)}"
                )
                signals.append(待推送信号(推送时间_ms=推送时间, 文本=文案, 去重键=f"30m_up@{bar.结束时间_ms}"))

        # 下穿：1h 收敛阈值=1500
        if float(bar.低) < float(dn):
            有1h收敛 = self._是否满足_ma收敛_最近N根(self._ind_1h, n=self._回看根数, threshold=self._阈值_1h_dn)
            if 有1h收敛:
                文案 = (
                    f"布林 九号策略信号：1小时均线相差小于{int(self._阈值_1h_dn)}，前一周期下穿布林轨。\n"
                    f"交易对: {self.交易对}\n"
                    f"触发周期: 30m\n"
                    f"触发时间: {_格式化时间(bar.结束时间_ms)}"
                )
                signals.append(待推送信号(推送时间_ms=推送时间, 文本=文案, 去重键=f"30m_dn@{bar.结束时间_ms}"))

        return signals

    def _检查触发_1h(self, bar: 周期K线) -> list[待推送信号]:
        if not self._ind_1h.布林口开():
            return []
        up = self._ind_1h.最新布林上轨()
        dn = self._ind_1h.最新布林下轨()
        if up is None or dn is None:
            return []

        有4h收敛 = self._是否满足_ma收敛_最近N根(self._ind_4h, n=self._回看根数, threshold=self._阈值_4h)
        if not 有4h收敛:
            return []

        signals: list[待推送信号] = []
        推送时间 = int(bar.结束时间_ms + 60_000)

        if float(bar.高) > float(up):
            文案 = (
                f"布林 九号策略信号：4小时均线相差小于{int(self._阈值_4h)}，前一周期上穿布林轨。\n"
                f"交易对: {self.交易对}\n"
                f"触发周期: 1h\n"
                f"触发时间: {_格式化时间(bar.结束时间_ms)}"
            )
            signals.append(待推送信号(推送时间_ms=推送时间, 文本=文案, 去重键=f"1h_up@{bar.结束时间_ms}"))

        if float(bar.低) < float(dn):
            文案 = (
                f"布林 九号策略信号：4小时均线相差小于{int(self._阈值_4h)}，前一周期下穿布林轨。\n"
                f"交易对: {self.交易对}\n"
                f"触发周期: 1h\n"
                f"触发时间: {_格式化时间(bar.结束时间_ms)}"
            )
            signals.append(待推送信号(推送时间_ms=推送时间, 文本=文案, 去重键=f"1h_dn@{bar.结束时间_ms}"))

        return signals

    def _检查触发_4h(self, bar: 周期K线) -> list[待推送信号]:
        if not self._ind_4h.布林口开():
            return []
        up = self._ind_4h.最新布林上轨()
        dn = self._ind_4h.最新布林下轨()
        if up is None or dn is None:
            return []

        # 日线 MA 收敛门槛：最近 N 根日线里出现过一次
        diffs = self._最近N根日线_ma_diff(self._回看根数)
        有1d收敛 = bool(diffs and any(d < float(self._阈值_1d) for d in diffs))
        if not 有1d收敛:
            return []

        signals: list[待推送信号] = []
        推送时间 = int(bar.结束时间_ms + 60_000)

        if float(bar.高) > float(up):
            文案 = (
                f"布林 九号策略信号：1天均线相差小于{int(self._阈值_1d)}，前一周期上穿布林轨。\n"
                f"交易对: {self.交易对}\n"
                f"触发周期: 4h\n"
                f"触发时间: {_格式化时间(bar.结束时间_ms)}"
            )
            signals.append(待推送信号(推送时间_ms=推送时间, 文本=文案, 去重键=f"4h_up@{bar.结束时间_ms}"))

        if float(bar.低) < float(dn):
            文案 = (
                f"布林 九号策略信号：1天均线相差小于{int(self._阈值_1d)}，前一周期下穿布林轨。\n"
                f"交易对: {self.交易对}\n"
                f"触发周期: 4h\n"
                f"触发时间: {_格式化时间(bar.结束时间_ms)}"
            )
            signals.append(待推送信号(推送时间_ms=推送时间, 文本=文案, 去重键=f"4h_dn@{bar.结束时间_ms}"))

        return signals
