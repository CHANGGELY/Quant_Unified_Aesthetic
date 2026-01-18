# -*- coding: utf-8 -*-
"""
env_kit.py - 统一的环境变量/.env 加载工具

这个文件是干嘛的？
    你可以把 `.env` 理解成“配置小本子”：
    - 里面写着 API Key、代理、运行模式等配置
    - 程序启动时把这些配置读进来，就不用每次都手动 export

为什么要做成“统一工具”？
    现在仓库里很多脚本都会写一份自己的“加载 .env 的代码”：
    - 复制粘贴多了，规则容易不一致
    - 最常见的坑：脚本在深层目录里，`.env` 在上层目录，导致“明明有 Key 但读不到”

这个工具的规则（不覆盖系统环境变量）：
    1) 优先加载：起点目录（通常是策略目录）的 `.env`
    2) 向上查找：最近的一个 `.env`（通常是 `Quant_Unified/.env`）
    3) 全程 override=False（系统环境变量优先）
    
重要约定（唯一入口）：
    - 代码只读取“系统环境变量”
    - `.env` 仅用于本地开发时，把内容自动写进系统环境变量

术语解释：
    - override=False：意思是“如果系统里已经有同名环境变量，就不要用 .env 覆盖它”
      类比：你已经在电脑系统设置里写好了密码，就不要再用小本子把它盖掉。
"""

from __future__ import annotations

from pathlib import Path


def _解析起点目录(起点: str | Path) -> Path:
    p = Path(起点).expanduser().resolve()
    if p.is_file():
        return p.parent
    return p


def 加载_env文件(起点: str | Path) -> list[Path]:
    """
    加载 .env 文件，并返回“实际加载了哪些路径”。

    参数：
        起点：一般传 `__file__` 或某个目录路径
              - 传文件路径：会自动取它的父目录
              - 传目录路径：直接作为起点目录
    """
    try:
        from dotenv import load_dotenv
    except Exception:  # pragma: no cover
        return []

    起点目录 = _解析起点目录(起点)
    候选: list[Path] = []

    # 1) 策略目录/.env
    策略env = 起点目录 / ".env"
    if 策略env.is_file():
        候选.append(策略env)

    # 2) 向上找最近的 .env（全局兜底）
    for 上级目录 in 起点目录.parents:
        上级env = 上级目录 / ".env"
        if 上级env.is_file() and 上级env not in 候选:
            候选.append(上级env)
            break

    for 路径 in 候选:
        load_dotenv(dotenv_path=路径, override=False)

    return 候选


def 读取布尔环境变量(变量名: str, 默认值: bool = False) -> bool:
    """
    把环境变量安全地解析为 bool。

    允许的真值（大小写不敏感）：
        true / 1 / yes / y / on
    """
    import os

    raw = os.getenv(变量名)
    if raw is None:
        return bool(默认值)
    raw = raw.strip().lower()
    return raw in ("true", "1", "yes", "y", "on")
