# -*- coding: utf-8 -*-
"""
运行 CI 测试入口（unittest）

这个文件是干嘛的？
    仓库里有一些“需要 API Key 才能跑”的脚本（比如 test_api.py），它们不适合放进 CI。
    所以我们提供一个“白名单式”的测试入口：
      - 只跑纯离线、可重复、无需密钥的测试

运行方法：
    cd /Users/chuan/Desktop/xiangmu/客户端
    python3 -X utf8 Quant_Unified/测试用例/运行CI测试.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


def _加入Quant_Unified到sys_path() -> Path:
    当前文件 = Path(__file__).resolve()
    quant_root = 当前文件.parents[1]  # Quant_Unified
    repo_root = quant_root.parent

    # 兼容三种常见 import 风格（历史原因）：
    # 1) import 策略仓库.xxx
    # 2) import common_core.xxx
    # 3) import Quant_Unified.基础库.xxx（老测试里还在用）
    候选路径 = [
        repo_root,
        quant_root,
        quant_root / "基础库",
    ]
    for p in 候选路径:
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
    return quant_root


def _discover(start_dir: Path, pattern: str = "test_*.py") -> unittest.TestSuite:
    loader = unittest.TestLoader()
    return loader.discover(start_dir=str(start_dir), pattern=pattern)


def main() -> None:
    quant_root = _加入Quant_Unified到sys_path()

    # 只跑“明确安全”的测试目录（避免误跑需要 API Key 的脚本）
    suites: list[unittest.TestSuite] = [
        _discover(quant_root / "测试用例"),
        _discover(quant_root / "基础库" / "common_core" / "tests"),
        _discover(quant_root / "基础库" / "common_core" / "risk_ctrl"),
    ]

    all_suite = unittest.TestSuite(suites)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(all_suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
