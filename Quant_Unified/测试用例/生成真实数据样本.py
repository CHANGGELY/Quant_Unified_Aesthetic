# -*- coding: utf-8 -*-
"""
生成真实数据样本（给 CI / 单元测试用）

这个脚本是干嘛的？
    我们的策略测试（比如 8号香农的“指标一致性测试”）需要一段真实行情数据。
    但完整的分钟级历史数据非常大，不适合直接提交到 GitHub。

所以我们做一个折中：
    - 从你本地的“大 H5 历史行情文件”里截取一小段
    - 保存成一个很小的 .npz（numpy 压缩文件）
    - 把这个小文件提交到仓库，让 CI 也能跑测试

重要原则：
    这里生成的是“真实行情的切片”，不是 Mock Data（模拟数据）。

运行方法：
    cd /Users/chuan/Desktop/xiangmu/客户端
    python3 -X utf8 Quant_Unified/测试用例/生成真实数据样本.py \
      --src 数据/历史行情中心/分钟K线/ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5 \
      --start 2021-05-17 --end 2021-05-23 \
      --out Quant_Unified/测试用例/真实数据样本/ETHUSDT_1m_2021-05-17_to_2021-05-23.npz
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def _读取H5切片(
    *,
    src: Path,
    dataset: str,
    time_col: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, np.ndarray]:
    import hdf5plugin  # noqa: F401  # 注册压缩插件
    import h5py

    if not src.exists():
        raise FileNotFoundError(f"❌ 找不到源数据文件: {src}")

    with h5py.File(str(src), "r") as f:
        if dataset not in f:
            raise KeyError(f"❌ dataset 不存在: {dataset}")
        table = f[dataset]

        # 只读时间列做索引定位（减少一次性读全表的内存压力）
        data_all = table[:]

    if time_col not in data_all.dtype.names:
        raise KeyError(f"❌ time_col 不存在: {time_col}, 实际={data_all.dtype.names}")

    t_ns = data_all[time_col].astype("int64", copy=False)
    t = pd.to_datetime(t_ns, unit="ns")

    start64 = np.datetime64(start.to_datetime64())
    end64 = np.datetime64(end.to_datetime64())
    mask = (t.to_numpy() >= start64) & (t.to_numpy() <= end64)
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        raise ValueError(f"❌ 在范围内找不到数据: {start}~{end}")

    sl = slice(int(idx[0]), int(idx[-1]) + 1)
    seg = data_all[sl]

    out: dict[str, np.ndarray] = {
        "candle_begin_time_ns": seg[time_col].astype("int64", copy=False),
        "open": seg["open"].astype("float64", copy=False),
        "high": seg["high"].astype("float64", copy=False),
        "low": seg["low"].astype("float64", copy=False),
        "close": seg["close"].astype("float64", copy=False),
        "volume": seg["volume"].astype("float64", copy=False),
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="从大 H5 历史行情里截取真实样本，保存为 .npz")
    parser.add_argument("--src", type=str, required=True, help="源 H5 文件路径")
    parser.add_argument("--dataset", type=str, default="klines/table", help="H5 dataset 路径（默认 klines/table）")
    parser.add_argument("--time-col", dest="time_col", type=str, default="candle_begin_time_GMT8", help="时间列（ns）")
    parser.add_argument("--start", type=str, required=True, help="起始日期（例如 2021-05-17）")
    parser.add_argument("--end", type=str, required=True, help="结束日期（例如 2021-05-23）")
    parser.add_argument("--out", type=str, required=True, help="输出 npz 文件路径")
    args = parser.parse_args()

    src = Path(args.src).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end) + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)

    print(f"📦 源文件: {src}")
    print(f"🧩 dataset: {args.dataset} | time_col: {args.time_col}")
    print(f"🗓️ 区间: {start} ~ {end}")
    print(f"🧾 输出: {out}")

    arr = _读取H5切片(src=src, dataset=args.dataset, time_col=args.time_col, start=start, end=end)
    n = len(arr["close"])
    print(f"✅ 读取成功: {n:,} 条")

    np.savez_compressed(out, **arr)
    size_kb = out.stat().st_size / 1024.0
    print(f"✅ 写入完成: {out} | {size_kb:.1f} KB")


if __name__ == "__main__":
    main()

