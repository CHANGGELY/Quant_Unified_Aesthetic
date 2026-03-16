# -*- coding: utf-8 -*-
"""
十号隐马尔可夫策略 - 数据读取（zip -> 单币K线 DataFrame）

为什么要单独写这个文件？
    你给的数据是一个 zip 压缩包，里面有 700+ 个 csv（每个币一份）。
    我们不想手动解压、也不想把数据复制来复制去，
    所以这里提供一个“直接从 zip 读 csv”的工具层。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import zipfile

import pandas as pd


@dataclass(frozen=True)
class K线数据列:
    时间列: str = "candle_begin_time"
    开: str = "open"
    高: str = "high"
    低: str = "low"
    收: str = "close"
    成交量: str = "volume"
    成交额: str = "quote_volume"


def 列出zip内csv文件(zip路径: Path) -> list[str]:
    if zip路径 is None:
        raise ValueError("zip路径 不能为空")
    zip路径 = Path(zip路径)
    if not zip路径.exists():
        raise FileNotFoundError(f"未找到数据zip: {zip路径}")

    with zipfile.ZipFile(zip路径) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv") and not n.endswith("/")]
    names.sort()
    return names


def 读取单币小时K线(
    *,
    zip路径: Path,
    文件名: str,
    列: K线数据列 | None = None,
) -> pd.DataFrame:
    """
    从 zip 中读取某个币的 1h K 线 csv。

    注意：
        这个数据源的 csv 第一行是“说明文字”，不是表头，所以要 skiprows=1。
        且编码是 gbk（不然会乱码/报错）。
    """
    if 列 is None:
        列 = K线数据列()
    zip路径 = Path(zip路径)

    usecols = [
        列.时间列,
        列.开,
        列.高,
        列.低,
        列.收,
        列.成交量,
        列.成交额,
        "symbol",
    ]

    with zipfile.ZipFile(zip路径) as z:
        with z.open(文件名) as f:
            df = pd.read_csv(
                f,
                encoding="gbk",
                skiprows=1,
                parse_dates=[列.时间列],
                usecols=usecols,
            )

    df.drop_duplicates(subset=[列.时间列], inplace=True, keep="last")
    df.sort_values(by=[列.时间列], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def 迭代读取多个币种(
    *,
    zip路径: Path,
    文件名列表: Iterable[str],
) -> Iterable[tuple[str, pd.DataFrame]]:
    for name in 文件名列表:
        yield name, 读取单币小时K线(zip路径=zip路径, 文件名=name)

