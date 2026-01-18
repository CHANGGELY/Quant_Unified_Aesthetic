# -*- coding: utf-8 -*-
"""
h5_klines.py - HDF5（层级数据文件）分钟K线数据定位器

这个文件是干嘛的？
    你现在仓库里有很多脚本把数据路径写死成：
        /Users/xxx/Desktop/xxx/ETHUSDT_1m_xxx.h5
    这会导致：
        - 换一台电脑就找不到文件（路径不同）
        - 部署到服务器更不可能（服务器没有你的桌面路径）

所以这里提供“统一数据定位”：
    - 代码只关心：我要哪个文件名
    - 这个模块负责：去一组“约定的目录”里按顺序查找

术语解释：
    - HDF5：一种适合存大表格/大数组的文件格式（像“压缩过的数据库文件”）
"""

from __future__ import annotations

import os
from pathlib import Path


def 获取Quant_Unified根目录() -> Path:
    """
    通过当前文件位置，向上找到 `Quant_Unified/` 的真实路径。
    """
    p = Path(__file__).resolve()
    for parent in p.parents:
        if parent.name == "Quant_Unified":
            return parent
    raise RuntimeError("❌ 无法定位 Quant_Unified 根目录（请检查项目目录结构）")


def 生成分钟K线文件名(
    交易对: str,
    *,
    周期: str = "1m",
    开始日期: str = "2019-11-01",
    结束日期: str = "2025-06-15",
    带table后缀: bool = True,
) -> str:
    """
    生成项目里常见的分钟线 H5 文件名。

    示例：
        ETHUSDT_1m_2019-11-01_to_2025-06-15_table.h5
    """
    交易对 = str(交易对).strip().upper()
    周期 = str(周期).strip()
    suffix = "_table.h5" if 带table后缀 else ".h5"
    return f"{交易对}_{周期}_{开始日期}_to_{结束日期}{suffix}"


def 获取分钟K线H5文件(文件名: str) -> Path:
    """
    按约定目录顺序查找分钟线 H5 文件，找到就返回 Path，找不到就抛异常。

    支持环境变量覆盖：
        - QUANT_H5_DATA_DIR：如果你想把数据放到其它硬盘/目录，设置它即可
    """
    文件名 = str(文件名).strip()
    if not 文件名:
        raise ValueError("文件名不能为空")

    quant_root = 获取Quant_Unified根目录()

    自定义目录 = os.getenv("QUANT_H5_DATA_DIR", "").strip()
    候选目录: list[Path] = []
    if 自定义目录:
        候选目录.append(Path(自定义目录).expanduser().resolve())

    # 推荐新位置：Quant_Unified/data/历史K线_H5
    候选目录.append(quant_root / "data" / "历史K线_H5")

    # 兼容旧位置（逐步迁移中）
    候选目录.append(quant_root / "策略仓库" / "二号网格策略" / "data_center")
    候选目录.append(quant_root / "策略仓库" / "4 号做市策略")  # 旧策略目录里也可能放了 .h5

    for 目录 in 候选目录:
        p = 目录 / 文件名
        if p.is_file():
            return p

    # 兜底：全仓库搜索（慢，但只在“真找不到”时触发）
    for p in quant_root.rglob(文件名):
        if p.is_file():
            return p

    raise FileNotFoundError(
        "❌ 找不到分钟K线 H5 文件：\n"
        f"   文件名: {文件名}\n"
        f"   已查找目录: {', '.join(str(d) for d in 候选目录)}\n"
        "   你可以：\n"
        "   1) 把文件放到 Quant_Unified/data/历史K线_H5/\n"
        "   2) 或设置环境变量 QUANT_H5_DATA_DIR 指向你的数据目录"
    )

