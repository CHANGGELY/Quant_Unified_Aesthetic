# -*- coding: utf-8 -*-
"""
十号隐马尔可夫策略 - 选币入口（输出未来8小时上涨/下跌概率 Top10%）

运行：
    python3 -X utf8 Quant_Unified/策略仓库/十号隐马尔可夫策略/select_coins.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ====== 自动把 Quant_Unified 加入 sys.path ======
CURRENT_FILE = Path(__file__).resolve()
QUANT_UNIFIED_ROOT = CURRENT_FILE.parents[2]
if str(QUANT_UNIFIED_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_UNIFIED_ROOT))

from 策略仓库.十号隐马尔可夫策略.config import Config
from 策略仓库.十号隐马尔可夫策略.program.数据读取 import 列出zip内csv文件, 读取单币小时K线
from 策略仓库.十号隐马尔可夫策略.program.推断 import 推断单币
from 策略仓库.十号隐马尔可夫策略.program.模型产物 import 加载产物


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
    模型路径 = cfg.模型目录 / "hmm10_gaussian.pkl"
    if not 模型路径.exists():
        raise FileNotFoundError(f"未找到模型文件: {模型路径}，请先运行 train.py")

    art = 加载产物(模型路径)
    print("🧠 十号隐马尔可夫策略 - 开始选币")
    print(f"📦 数据zip: {cfg.数据zip路径}")
    print(f"📦 模型文件: {模型路径}")

    文件列表 = 列出zip内csv文件(cfg.数据zip路径)
    文件列表 = [n for n in 文件列表 if n.endswith("-USDT.csv")]
    文件列表.sort()

    # 先找一个“共同截止时间”：避免某些币数据更新更晚造成不公平
    last_times: list[pd.Timestamp] = []
    抽样数 = int(cfg.截止时间抽样币种数) if getattr(cfg, "截止时间抽样币种数", 0) else 80
    for fname in 文件列表[: max(1, min(len(文件列表), 抽样数))]:
        df = 读取单币小时K线(zip路径=cfg.数据zip路径, 文件名=fname)
        df = _清洗并补全小时序列(df)
        last_times.append(pd.to_datetime(df["candle_begin_time"].iloc[-1]))

    if last_times:
        q = float(getattr(cfg, "截止时间分位数", 0.2))
        q = min(max(q, 0.0), 1.0)
        ns = np.array([t.value for t in last_times], dtype=np.int64)
        cutoff_ns = int(np.quantile(ns, q))
        截止时间 = pd.Timestamp(cutoff_ns).floor("h")
    else:
        截止时间 = pd.Timestamp.utcnow().floor("h")

    if getattr(cfg, "最大推断币种数", 0):
        文件列表 = 文件列表[: int(cfg.最大推断币种数)]

    结果列表 = []
    for i, fname in enumerate(文件列表, 1):
        if i % 50 == 0:
            print(f"⏳ 进度: {i}/{len(文件列表)}")
        df = 读取单币小时K线(zip路径=cfg.数据zip路径, 文件名=fname)
        df = _清洗并补全小时序列(df)
        # 如果该币在“共同截止时间”之前就没数据了（例如下架/合约停了），就不参与这一轮横截面对比
        if pd.to_datetime(df["candle_begin_time"].iloc[-1]) < 截止时间:
            continue

        res = 推断单币(
            df=df,
            产物=art,
            截止时间=截止时间,
            推断回看小时数=cfg.推断回看小时数,
            预测步长小时=cfg.预测步长小时,
            震荡阈值_8小时对数收益=cfg.震荡阈值_8小时对数收益,
        )
        if res is None or not res.symbol:
            continue
        结果列表.append(res)

    if not 结果列表:
        raise RuntimeError("没有产生任何预测结果")

    out = pd.DataFrame([r.__dict__ for r in 结果列表])
    out.sort_values(["上涨概率"], ascending=False, inplace=True)
    out.reset_index(drop=True, inplace=True)

    n = max(1, int(np.ceil(len(out) * cfg.多头选币比例)))
    多头 = out.nlargest(n, "上涨概率")[["symbol", "上涨概率", "震荡概率", "下跌概率", "最新价格", "截止时间"]]
    空头 = out.nlargest(n, "下跌概率")[["symbol", "下跌概率", "震荡概率", "上涨概率", "最新价格", "截止时间"]]

    print("\n✅ 多头（上涨概率 Top10%）:")
    print(多头.head(30).to_string(index=False))
    print("\n✅ 空头（下跌概率 Top10%）:")
    print(空头.head(30).to_string(index=False))

    cfg.缓存目录.mkdir(parents=True, exist_ok=True)
    out_path = cfg.缓存目录 / f"选币结果_{截止时间.strftime('%Y%m%d_%H%M%S')}.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n💾 全量预测已保存: {out_path}")


if __name__ == "__main__":
    main()
