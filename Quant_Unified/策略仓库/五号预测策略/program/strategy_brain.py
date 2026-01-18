# -*- coding: utf-8 -*-
"""
五号预测策略 - “策略脑子”（盘口驱动 + 机器学习输出信号）

这个文件是干嘛的？
    五号策略的特点是“偏高频”：
    - 输入不是 1 分钟 K 线，而是 L2 盘口（Level 2：多档位盘口深度）快照
    - 输出不是“挂很多限价单”，而是“我想做多/做空/空仓”（目标仓位）

为什么要单独做一个“脑子”文件？
    你现在的目标架构是：
        策略（脑子）只负责决策：看到行情 -> 输出目标仓位
        执行器（手脚）负责执行：回测撮合/实盘下单/爆仓检查/成本扣减

    所以这里实现 common_core.strategy 的「盘口策略接口」：
        - 在盘口快照：输入一帧盘口 + 当前账户 -> 输出目标仓位（或 None 表示无需动作）

重要约定（为了让回测更贴近实盘）：
    - 模型推理默认按 1s 口径运行（inference_interval_ms=1000）：
      如果你用 100ms 的深度流喂策略，我们会“每秒取最后一帧快照”再推理，
      避免拿 100ms 数据去喂 1s 训练出来的模型导致口径错位。
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# ====== 自动把 Quant_Unified 加入 sys.path（保证 joblib 能加载包含“策略仓库.*”的模型对象） ======
# 说明：
#   你保存的模型（*.pkl）里会记录 TrainArtifacts 的“模块路径”，例如：
#       策略仓库.五号预测策略.program.step3_train_calibrate.TrainArtifacts
#   所以在加载模型时，Python 必须能 import 到 `策略仓库` 这个包。
CURRENT_FILE = Path(__file__).resolve()
QUANT_UNIFIED_ROOT = CURRENT_FILE.parents[3]
if str(QUANT_UNIFIED_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_UNIFIED_ROOT))

from 基础库.common_core.strategy import (
    K线,
    盘口快照,
    账户状态,
    策略输出,
    目标仓位,
    仓位方向,
    盘口策略接口,
)


@dataclass(slots=True)
class _滚动统计窗口:
    """
    一个非常轻量的“滚动窗口”工具（用环形数组实现）

    用人话说：
        你可以把它想成一个固定长度的小队列：
        - 新数据进来就塞进去
        - 队列满了就把最老的数据挤出去

    我们用它来计算：
        - 均值（例如 MA60：60 秒移动平均）
        - 标准差（例如 ret_std_10：10 秒收益率波动）
        - 最大/最小（例如 hl_range_10：10 秒最高最低范围）
    """

    窗口长度: int
    buf: np.ndarray
    pos: int = 0
    count: int = 0
    sum: float = 0.0
    sumsq: float = 0.0

    @classmethod
    def 创建(cls, 窗口长度: int) -> "_滚动统计窗口":
        if 窗口长度 <= 0:
            raise ValueError("窗口长度 必须 > 0")
        return cls(窗口长度=int(窗口长度), buf=np.zeros(int(窗口长度), dtype=np.float64))

    def 推入(self, x: float, *, 记录平方和: bool = True) -> None:
        x = float(x)
        if self.count < self.窗口长度:
            self.buf[self.pos] = x
            self.sum += x
            if 记录平方和:
                self.sumsq += x * x
            self.pos = (self.pos + 1) % self.窗口长度
            self.count += 1
            return

        old = float(self.buf[self.pos])
        self.sum -= old
        if 记录平方和:
            self.sumsq -= old * old

        self.buf[self.pos] = x
        self.sum += x
        if 记录平方和:
            self.sumsq += x * x
        self.pos = (self.pos + 1) % self.窗口长度

    @property
    def 是否已满(self) -> bool:
        return self.count >= self.窗口长度

    def 均值(self) -> float:
        if self.count <= 0:
            return float("nan")
        return float(self.sum / float(self.count))

    def 标准差(self) -> float:
        if self.count <= 1:
            return float("nan")
        # pandas 的 rolling.std 默认 ddof=1（样本标准差），这里对齐它的口径：
        # var = (Σx^2 - (Σx)^2/n) / (n-1)
        n = float(self.count)
        numerator = float(self.sumsq - (self.sum * self.sum) / n)
        var = numerator / max(n - 1.0, 1.0)
        return float(math.sqrt(max(var, 0.0)))

    def 最大值(self) -> float:
        if self.count <= 0:
            return float("nan")
        if self.count < self.窗口长度:
            return float(np.max(self.buf[: self.count]))
        return float(np.max(self.buf))

    def 最小值(self) -> float:
        if self.count <= 0:
            return float("nan")
        if self.count < self.窗口长度:
            return float(np.min(self.buf[: self.count]))
        return float(np.min(self.buf))


@dataclass(slots=True)
class _五号特征引擎_1s:
    """
    五号策略的 1s 特征引擎（增量口径）

    目标：
        和 `program/step2_build_dataset.py::build_features_1s` 的数学口径尽量一致，
        这样“训练用的特征”和“实盘推理用的特征”才不会跑偏。
    """

    depth_levels: int

    # 价格序列（用于滚动 max/min、MA、RSI）
    _wmp_win_10: _滚动统计窗口
    _wmp_win_60: _滚动统计窗口

    # 收益率序列（pct_change）
    _ret_win_10: _滚动统计窗口

    # RSI：滚动平均 gain/loss（window=14）
    _gain_win_14: _滚动统计窗口
    _loss_win_14: _滚动统计窗口

    _prev_wmp: float = 0.0

    @classmethod
    def 创建(cls, depth_levels: int) -> "_五号特征引擎_1s":
        return cls(
            depth_levels=int(max(1, depth_levels)),
            _wmp_win_10=_滚动统计窗口.创建(10),
            _wmp_win_60=_滚动统计窗口.创建(60),
            _ret_win_10=_滚动统计窗口.创建(10),
            _gain_win_14=_滚动统计窗口.创建(14),
            _loss_win_14=_滚动统计窗口.创建(14),
        )

    def 更新并计算(self, 快照: 盘口快照) -> dict[str, float] | None:
        # ====== 1) 基础价格 ======
        bid1_p = float(快照.买一价())
        ask1_p = float(快照.卖一价())
        if bid1_p <= 0.0 or ask1_p <= 0.0:
            return None

        bid1_q = float(快照.bid量[0]) if 快照.bid量 else 0.0
        ask1_q = float(快照.ask量[0]) if 快照.ask量 else 0.0

        spread = float(ask1_p - bid1_p)
        mid = float((ask1_p + bid1_p) * 0.5)

        denom = bid1_q + ask1_q
        if denom <= 0.0:
            return None

        # WMP：Weighted Mid Price（加权中间价）
        wmp = float(ask1_p * (bid1_q / denom) + bid1_p * (ask1_q / denom))
        if wmp <= 0.0 or not math.isfinite(wmp):
            return None

        # ====== 2) OBI（Order Book Imbalance：买卖盘不平衡）=====
        # 说明：
        #   OBI 越接近 +1，表示买盘更强；越接近 -1，表示卖盘更强。
        features: dict[str, float] = {}
        features["spread"] = spread

        features["obi_l1"] = float((bid1_q - ask1_q) / denom)

        # Deep OBI：L5/L10/L20/L50（只在深度足够时计算）
        for level in (5, 10, 20, 50):
            if self.depth_levels < level:
                continue
            bsum = float(sum(float(x) for x in 快照.bid量[:level]))
            asum = float(sum(float(x) for x in 快照.ask量[:level]))
            d = bsum + asum
            features[f"obi_l{level}"] = float((bsum - asum) / d) if d > 0.0 else float("nan")

            # 兼容旧特征：obi_decay 只对 L5 做
            if level == 5:
                n = min(5, self.depth_levels)
                weights = (1.0, 0.8, 0.6, 0.4, 0.2)[:n]
                bid_decay = float(sum(float(快照.bid量[i]) * weights[i] for i in range(n)))
                ask_decay = float(sum(float(快照.ask量[i]) * weights[i] for i in range(n)))
                d2 = bid_decay + ask_decay
                features["obi_decay"] = float((bid_decay - ask_decay) / d2) if d2 > 0.0 else float("nan")

        # ====== 3) 波动率与动量特征（全部增量更新）=====
        # pct_change：ret = wmp / prev - 1
        ret = float("nan")
        if self._prev_wmp > 0.0:
            ret = float(wmp / self._prev_wmp - 1.0)
        self._prev_wmp = wmp

        # 价格窗口更新
        self._wmp_win_10.推入(wmp, 记录平方和=False)
        self._wmp_win_60.推入(wmp, 记录平方和=False)

        # 10 秒收益率波动
        if math.isfinite(ret):
            self._ret_win_10.推入(ret, 记录平方和=True)

        features["ret_std_10"] = float(self._ret_win_10.标准差())

        # 10 秒最高最低范围
        roll_max = self._wmp_win_10.最大值()
        roll_min = self._wmp_win_10.最小值()
        features["hl_range_10"] = float((roll_max - roll_min) / wmp) if wmp > 0.0 else float("nan")

        # MA60 偏离率
        ma_60 = self._wmp_win_60.均值()
        features["dev_ma_60"] = float((wmp - ma_60) / ma_60) if ma_60 and math.isfinite(ma_60) else float("nan")

        # RSI14（Rolling Mean 口径）
        if self._wmp_win_60.count >= 2:
            # delta = 当前 wmp - 上一 wmp
            # 注意：我们这里只有 prev_wmp（已更新），所以用 buf 取上一条更稳
            # _wmp_win_60.buf 里保存的是数值，但环形数组不保证顺序，
            # 为了避免复杂，我们直接用 ret 反推 delta 也可以：
            #   ret = wmp/prev - 1 -> prev = wmp/(1+ret) -> delta = wmp - prev
            if math.isfinite(ret) and ret > -1.0:
                prev = wmp / (1.0 + ret)
                delta = wmp - prev
                gain = float(delta) if delta > 0.0 else 0.0
                loss = float(-delta) if delta < 0.0 else 0.0
                self._gain_win_14.推入(gain, 记录平方和=False)
                self._loss_win_14.推入(loss, 记录平方和=False)

        rsi = float("nan")
        if self._gain_win_14.是否已满 and self._loss_win_14.是否已满:
            avg_gain = self._gain_win_14.均值()
            avg_loss = self._loss_win_14.均值()
            if avg_loss > 0.0 and math.isfinite(avg_gain) and math.isfinite(avg_loss):
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
        features["rsi_14"] = float(rsi)

        # ====== 4) 只有当窗口都“够长”时才输出（对齐训练 dropna 口径）=====
        if not self._wmp_win_10.是否已满:
            return None
        if not self._ret_win_10.是否已满:
            return None
        if not self._wmp_win_60.是否已满:
            return None
        if not self._gain_win_14.是否已满 or not self._loss_win_14.是否已满:
            return None

        # 额外的 meta（便于回测/实盘日志观察，不参与训练特征时也无害）
        features["wmp"] = wmp
        features["mid"] = mid
        features["bid1_p"] = bid1_p
        features["ask1_p"] = ask1_p
        return features


class 五号预测策略脑子(盘口策略接口):
    """
    五号预测策略脑子（盘口驱动）
    """

    def __init__(self, config) -> None:
        self._config = config
        self._symbol = str(getattr(config, "symbol", "") or "").upper().strip()
        if not self._symbol:
            raise ValueError("❌ 五号策略需要配置 symbol（例如 BTCUSDT）")

        self._leverage = float(getattr(config, "leverage", 1.0) or 1.0)
        if self._leverage < 0:
            raise ValueError("❌ leverage 必须 >= 0")

        self._depth_levels = int(getattr(config, "depth_levels", 20) or 20)
        self._推理间隔_ms = int(getattr(config, "inference_interval_ms", 1000) or 1000)
        if self._推理间隔_ms <= 0:
            raise ValueError("❌ inference_interval_ms 必须是正整数")

        self._p_enter = float(getattr(config, "p_enter", 0.55))
        self._p_exit = float(getattr(config, "p_exit", 0.55))
        self._diff_enter = float(getattr(config, "diff_enter", 0.0))
        self._diff_exit = float(getattr(config, "diff_exit", 0.0))

        self._label_threshold = float(getattr(config, "label_threshold", 0.0005) or 0.0005)
        self._model_mode = str(getattr(config, "model_mode", "executable") or "executable").strip()
        self._model_horizon_s = int(getattr(config, "model_horizon_s", 10) or 10)

        self._模型 = self._加载模型()
        self._模型特征名 = self._提取特征名(self._模型)

        self._特征引擎 = _五号特征引擎_1s.创建(depth_levels=self._depth_levels)

        # “桶采样”状态：每个桶只取最后一帧快照，用来对齐 1s 口径
        self._当前桶: int | None = None
        self._桶内最后快照: 盘口快照 | None = None

        # 信号状态（-1/0/1）+ 上次输出（避免重复发同样的目标仓位）
        self._当前信号: int = 0
        self._上次输出方向: 仓位方向 = 仓位方向.空仓

    # ====== 策略接口 ======

    @property
    def 策略名称(self) -> str:
        return "五号预测策略（盘口 + 机器学习）"

    def 在K线收盘(self, k线: K线, 账户: 账户状态) -> 策略输出:
        # 五号策略的主驱动不是 K 线，这里返回“空动作”，保证接口完整。
        return 策略输出(备注={"提示": "五号策略使用盘口快照驱动，在K线收盘不做决策"})

    def 在价格更新(self, 时间_ms: int, 最新价: float, 账户: 账户状态) -> 策略输出 | None:
        # 五号策略不用“单价 tick”，它需要 L2 盘口快照。
        return None

    def 在成交回报(self, 回报) -> None:
        # 预测策略目前不依赖成交回报维护内部状态（执行器会管理持仓）。
        return

    # ====== 盘口扩展接口 ======

    def 在盘口快照(self, 快照: 盘口快照, 账户: 账户状态) -> 策略输出 | None:
        # Guard Clauses：输入异常直接挡住（绝不吞错）
        if 账户.账户权益 <= 0:
            return None

        # 1) “桶采样”：每秒只取最后一帧快照，避免口径错位
        bucket = int(快照.时间_ms // self._推理间隔_ms)
        if self._当前桶 is None:
            self._当前桶 = bucket
            self._桶内最后快照 = 快照
            return None

        if bucket == self._当前桶:
            self._桶内最后快照 = 快照
            return None

        # bucket 跳到了下一桶：对上一桶的“最后快照”做推理
        last = self._桶内最后快照
        self._当前桶 = bucket
        self._桶内最后快照 = 快照
        if last is None:
            return None

        features = self._特征引擎.更新并计算(last)
        if not features:
            return None

        输出方向, 备注 = self._用模型得到目标方向(features)
        if 输出方向 == self._上次输出方向:
            return None

        self._上次输出方向 = 输出方向

        return 策略输出(
            目标仓位=目标仓位(
                交易对=账户.交易对 or self._symbol,
                方向=输出方向,
                名义杠杆=float(self._leverage) if 输出方向 != 仓位方向.空仓 else 0.0,
            ),
            备注=备注,
        )

    # ====== 内部工具 ======

    def _定位策略目录(self) -> Path:
        # 当前文件：.../五号预测策略/program/strategy_brain.py
        return Path(__file__).resolve().parents[1]

    def _加载模型(self) -> Any:
        """
        只读真实模型文件；找不到就直接报错（拒绝 mock）。
        """
        强制路径 = os.environ.get("PREDICT5_MODEL_PATH", "").strip()
        if 强制路径:
            path = Path(强制路径).expanduser().resolve()
            if not path.exists():
                raise FileNotFoundError(f"❌ PREDICT5_MODEL_PATH 指向的模型文件不存在: {path}")
            return self._joblib_load(path)

        models_dir = self._定位策略目录() / "models"
        path = models_dir / f"{self._symbol}_{self._model_mode}_h{self._model_horizon_s}.pkl"
        if not path.exists():
            raise FileNotFoundError(
                "❌ 找不到模型文件，无法做真实推理（我们拒绝用假模型）。\n"
                f"期望路径: {path}\n"
                "你可以：\n"
                "1) 先运行五号策略的训练脚本生成模型；或\n"
                "2) 设置环境变量 PREDICT5_MODEL_PATH 指向你的真实模型文件。"
            )
        return self._joblib_load(path)

    @staticmethod
    def _joblib_load(path: Path) -> Any:
        import joblib

        return joblib.load(path)

    @staticmethod
    def _提取特征名(model_obj: Any) -> list[str]:
        if hasattr(model_obj, "feature_names"):
            names = list(getattr(model_obj, "feature_names"))
            if names:
                return [str(x) for x in names]
        # 兜底：部分模型（例如 lightgbm 回归）可能没有 feature_names
        raise ValueError("❌ 模型文件里缺少 feature_names，无法对齐特征列顺序")

    def _用模型得到目标方向(self, features: dict[str, float]) -> tuple[仓位方向, dict[str, Any]]:
        # 1) 组装特征向量（严格按训练时列顺序）
        x = np.asarray([float(features.get(name, float("nan"))) for name in self._模型特征名], dtype=np.float64)
        if not np.isfinite(x).all():
            return 仓位方向.空仓, {"跳过原因": "特征含 NaN/Inf"}

        x2 = x.reshape(1, -1)

        # 2) 两类模型兼容：
        #    - TrainArtifacts（多分类）：calibrated_model.predict_proba -> (down, hold, up)
        #    - 回归模型：predict -> 预测未来收益
        if hasattr(self._模型, "calibrated_model"):
            calibrated = getattr(self._模型, "calibrated_model")
            proba = np.asarray(calibrated.predict_proba(x2), dtype=float)
            p_down, p_hold, p_up = float(proba[0, 0]), float(proba[0, 1]), float(proba[0, 2])
            方向 = self._迟滞规则更新信号(p_up=p_up, p_down=p_down)
            return 方向, {
                "p_down": p_down,
                "p_hold": p_hold,
                "p_up": p_up,
                "signal": int(self._当前信号),
                "mode": str(self._model_mode),
                "horizon_s": int(self._model_horizon_s),
                "wmp": float(features.get("wmp", 0.0) or 0.0),
                "spread": float(features.get("spread", 0.0) or 0.0),
            }

        if hasattr(self._模型, "predict"):
            pred = float(np.asarray(self._模型.predict(x2), dtype=float).reshape(-1)[0])
            if pred > self._label_threshold:
                self._当前信号 = 1
            elif pred < -self._label_threshold:
                self._当前信号 = -1
            # 介于阈值之间：保持原信号（迟滞）
            方向 = 仓位方向.多 if self._当前信号 == 1 else 仓位方向.空 if self._当前信号 == -1 else 仓位方向.空仓
            return 方向, {
                "pred_return": pred,
                "signal": int(self._当前信号),
                "label_threshold": float(self._label_threshold),
                "wmp": float(features.get("wmp", 0.0) or 0.0),
                "spread": float(features.get("spread", 0.0) or 0.0),
            }

        return 仓位方向.空仓, {"跳过原因": "模型不支持 predict/predict_proba"}

    def _迟滞规则更新信号(self, *, p_up: float, p_down: float) -> 仓位方向:
        """
        复用回测里同款的迟滞规则（hysteresis：迟滞）

        你可以把它理解成“不要一有风吹草动就换方向”：
        - 进场要更严格
        - 换向也要更严格
        """
        up = float(p_up)
        down = float(p_down)
        if not math.isfinite(up) or not math.isfinite(down):
            return 仓位方向.空仓

        cur = int(self._当前信号)
        if cur == 0:
            if up >= self._p_enter and (up - down) >= self._diff_enter:
                cur = 1
            elif down >= self._p_enter and (down - up) >= self._diff_enter:
                cur = -1
        elif cur == 1:
            if down >= self._p_exit and (down - up) >= self._diff_exit:
                cur = -1
        else:
            if up >= self._p_exit and (up - down) >= self._diff_exit:
                cur = 1

        self._当前信号 = int(cur)
        return 仓位方向.多 if cur == 1 else 仓位方向.空 if cur == -1 else 仓位方向.空仓
