# -*- coding: utf-8 -*-
"""
十号隐马尔可夫策略 - 训练入口

运行：
    python3 -X utf8 Quant_Unified/策略仓库/十号隐马尔可夫策略/train.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

# ====== 自动把 Quant_Unified 加入 sys.path（保证能 import 到“基础库/策略仓库”） ======
CURRENT_FILE = Path(__file__).resolve()
QUANT_UNIFIED_ROOT = CURRENT_FILE.parents[2]
if str(QUANT_UNIFIED_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_UNIFIED_ROOT))

from 策略仓库.十号隐马尔可夫策略.config import Config
from 策略仓库.十号隐马尔可夫策略.program.数据读取 import 列出zip内csv文件, 读取单币小时K线
from 策略仓库.十号隐马尔可夫策略.program.特征工程 import 计算HMM特征
from 策略仓库.十号隐马尔可夫策略.program.模型产物 import 十号HMM训练产物, 保存产物


# ====== 杠杆币误杀白名单 ======
# 这些是真实的加密货币项目，名字恰好以 UP/DOWN/BEAR/BULL 结尾，但它们不是杠杆代币！
# 如果不加白名单，会被下面的杠杆币过滤规则误杀。
# 发现新的误杀币种时，请添加到这里（只写 base 部分，不带 USDT）。
_杠杆币误杀白名单 = frozenset({
    "JUP",      # Jupiter - Solana 生态的去中心化交易聚合器
    "SETUP",    # SetupCoin（如果存在）
    # 未来如果发现其他被误杀的真实项目，在这里追加...
})


def _是否可交易币种(symbol: str) -> bool:
    """
    判断一个交易对是否适合用于量化策略训练。

    【过滤逻辑】
    1. 必须是 USDT 计价的合约对（如 BTC-USDT、ETHUSDT）
    2. 排除隐藏的系统标记（以 "." 开头的符号）
    3. 排除"杠杆代币"（Leveraged Token）

    【什么是杠杆币？】
    杠杆币是交易所发行的衍生品代币，会自动放大标的资产的涨跌幅（通常 2-3 倍）。
    常见命名规则：
      - BTCUP / ETHUP     → 做多杠杆币（BTC涨1%，BTCUP涨约3%）
      - BTCDOWN / ETHDOWN → 做空杠杆币（BTC跌1%，BTCDOWN涨约3%）
      - BTCBULL / ETHBULL → 同 UP，做多方向
      - BTCBEAR / ETHBEAR → 同 DOWN，做空方向

    【为什么要过滤掉杠杆币？】
    1. 价格行为异常：杠杆币有"磨损效应"，长期持有必亏，不适合趋势策略
    2. 数据不纯净：它们是人造衍生品，价格走势被人为放大，会污染 HMM 模型学习
    3. 流动性差：交易量小，容易滑点
    """
    # ------ 基本格式校验 ------
    if not symbol or symbol.startswith("."):
        return False
    if not symbol.endswith("USDT"):
        return False

    # ------ 提取 base 币种名（去掉 USDT 后缀） ------
    # 兼容 "BTC-USDT" 和 "BTCUSDT" 两种格式
    base = symbol.upper().replace("-USDT", "USDT")[:-4]

    # ------ 杠杆币过滤 ------
    # 以 UP/DOWN/BEAR/BULL 结尾的，大概率是杠杆代币
    # 但要先检查白名单，避免误杀真实项目（如 JUP = Jupiter）
    if base.endswith(("UP", "DOWN", "BEAR", "BULL")):
        if base not in _杠杆币误杀白名单:
            return False

    return True


def _清洗并补全小时序列(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df = df.copy()
    df["candle_begin_time"] = pd.to_datetime(df["candle_begin_time"])
    df.drop_duplicates(subset=["candle_begin_time"], inplace=True, keep="last")
    df.sort_values("candle_begin_time", inplace=True)

    first = df["candle_begin_time"].min()
    last = df["candle_begin_time"].max()
    hourly = pd.DataFrame(pd.date_range(start=first, end=last, freq="1h"), columns=["candle_begin_time"])
    df = hourly.merge(df, on="candle_begin_time", how="left", sort=True)

    df["close"] = df["close"].ffill()
    df["open"] = df["open"].fillna(df["close"])
    df["high"] = df["high"].fillna(df["close"])
    df["low"] = df["low"].fillna(df["close"])
    df["volume"] = df["volume"].fillna(0.0)
    df["quote_volume"] = df["quote_volume"].fillna(0.0)
    df["symbol"] = df["symbol"].ffill()
    return df


def main() -> None:
    cfg = Config()
    print("🧠 十号隐马尔可夫策略 - 开始训练")
    print(f"📦 数据zip: {cfg.数据zip路径}")

    文件列表 = 列出zip内csv文件(cfg.数据zip路径)
    文件列表 = [n for n in 文件列表 if n.endswith("-USDT.csv")]

    # 稳定排序 + 打乱抽样（避免每次都只训练“字母表靠前”的币）
    rng = np.random.default_rng(cfg.随机种子)
    rng.shuffle(文件列表)

    选中 = []
    for name in 文件列表:
        symbol = Path(name).stem
        if _是否可交易币种(symbol):
            选中.append(name)
        if len(选中) >= cfg.最大训练币种数:
            break

    print(f"✅ 训练币种数: {len(选中)} / {cfg.最大训练币种数}")

    X_list: list[np.ndarray] = []
    lengths: list[int] = []
    feature_names: list[str] | None = None

    for i, fname in enumerate(选中, 1):
        print(f"📥 读取({i}/{len(选中)}): {fname}")
        df = 读取单币小时K线(zip路径=cfg.数据zip路径, 文件名=fname)
        df = _清洗并补全小时序列(df)

        if cfg.训练开始时间:
            df = df[df["candle_begin_time"] >= pd.to_datetime(cfg.训练开始时间)]
        if cfg.训练结束时间:
            df = df[df["candle_begin_time"] <= pd.to_datetime(cfg.训练结束时间)]

        if cfg.每币最多使用K线数 > 0 and len(df) > cfg.每币最多使用K线数:
            df = df.tail(cfg.每币最多使用K线数).copy()

        if len(df) < 50:
            continue

        feat = 计算HMM特征(df)
        if feature_names is None:
            feature_names = feat.特征名
        X_list.append(feat.特征矩阵)
        lengths.append(len(feat.特征矩阵))

    if not X_list:
        raise RuntimeError("没有可用的训练数据（可能是时间范围/过滤条件太严格）")

    X = np.concatenate(X_list, axis=0)
    print(f"📐 训练样本总行数: {len(X):,} | 特征维度: {X.shape[1]}")

    scaler = StandardScaler()
    Xz = scaler.fit_transform(X)

    # ====== 用 hmmlearn 的高斯 HMM（full 协方差）训练 ======
    # full 协方差 = 每个状态一个完整协方差矩阵，能学到特征之间的联动关系（你明确要求的口径）
    hmm = GaussianHMM(
        n_components=int(cfg.隐状态数),
        covariance_type="full",
        n_iter=int(cfg.最大迭代次数),
        tol=float(cfg.收敛阈值),
        random_state=int(cfg.随机种子),
        verbose=True,
        min_covar=float(cfg.方差下限),
    )
    hmm.fit(Xz, lengths=lengths)

    # ====== 状态 -> 标签 映射（按“收益均值”排序）======
    # 特征 0 是 log_ret_1h。
    # 注意：模型是在“标准化后的特征空间”训练的，所以这里把均值还原回真实对数收益口径，更直观。
    z_mean = np.asarray(hmm.means_, dtype=np.float64)[:, 0]
    scale0 = float(scaler.scale_[0])
    mean0 = float(scaler.mean_[0])
    ret_means = z_mean * scale0 + mean0
    order = np.argsort(ret_means)
    state_to_label = {
        int(order[0]): "下跌",
        int(order[1]): "震荡",
        int(order[2]): "上涨",
    }

    art = 十号HMM训练产物(
        特征名=feature_names or [],
        标准化器=scaler,
        模型=hmm,
        状态到标签=state_to_label,
    )

    cfg.模型目录.mkdir(parents=True, exist_ok=True)
    out_path = cfg.模型目录 / "hmm10_gaussian.pkl"
    保存产物(art, out_path)
    print(f"💾 训练产物已保存: {out_path}")
    print(f"🏷️ 状态映射: {state_to_label} | ret_mean_logret_1h={ret_means.tolist()}")


if __name__ == "__main__":
    main()
