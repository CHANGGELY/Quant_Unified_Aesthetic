# -*- coding: utf-8 -*-
"""
binance_raw.py - 币安期货 REST API（八号策略的“兼容层”）

这个文件是干嘛的？
    我们把“通用币安 REST API 实现”抽到了公共层：
        common_core.exchange.binance_raw

    但仓库里已经有很多脚本在 import：
        策略仓库.八号香农策略.api.binance_raw

    所以这里保留一个“薄封装”，只做两件事：
        1) 先加载八号策略目录下的 `.env`（本地开发的自动填充器）
        2) 再把公共层的 API 全部 re-export（重新导出），保证旧代码完全不需要改

重要约定（唯一入口仍是系统环境变量）：
    - 代码运行时只读取系统环境变量
    - `.env` 只是本地开发时把内容塞进环境变量，且 `override=False`（不会覆盖你手动 export 的值）
"""

from __future__ import annotations

from common_core.utils.env_kit import 加载_env文件

_ = 加载_env文件(__file__)

# re-export（重新导出）：保持旧 import 不变
from common_core.exchange.binance_raw import *  # noqa: F401,F403

