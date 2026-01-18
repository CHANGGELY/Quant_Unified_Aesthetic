# -*- coding: utf-8 -*-
"""
一号择时策略 - 策略接口版回测入口（脑子 + 执行器）

这个文件是干嘛的？
    把“一号择时策略”的回测流程拆成两段：
        1) 策略脑子：算因子 -> 选币 -> 输出目标权重（选币结果）
        2) 回测执行器：按目标权重做调仓撮合 -> 扣成本 -> 检查爆仓 -> 输出资金曲线与报告

为什么要这么拆？
    你可以把它类比成：
        - 脑子：负责决定“买哪些、卖哪些、各占多少”
        - 执行器：负责把决定真的执行出来，并且随时看“保证金够不够”（不够就爆仓）

运行方法（建议在 Quant_Unified 下执行）：
    cd /Users/chuan/Desktop/xiangmu/客户端/Quant_Unified
    python3 -X utf8 策略仓库/一号择时策略/select-coin-feat-long_short_compose/backtest_interface.py --no-chart
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _注入项目路径() -> None:
    """
    让脚本“无论从哪里运行”都能找到项目的公共库。

    解释：
        Python 默认只认识“当前脚本所在目录”。
        但我们的公共库在 Quant_Unified/基础库、Quant_Unified/服务 等目录里，
        所以这里把它们加入 sys.path（模块搜索路径）。
    """

    current = Path(__file__).resolve()
    quant_root = current.parents[3]  # Quant_Unified

    for folder in ["基础库", "服务", "策略仓库", "应用"]:
        p = quant_root / folder
        if p.exists() and str(p) not in sys.path:
            sys.path.append(str(p))
    if str(quant_root) not in sys.path:
        sys.path.append(str(quant_root))


def main() -> None:
    _注入项目路径()

    from core.model.backtest_config import load_config
    from program.step4_simulate_performance import simulate_performance
    from program.strategy_brain import 一号择时脑子运行参数, 一号择时策略脑子

    parser = argparse.ArgumentParser(description="一号择时策略（脑子 + 执行器）接口版回测")
    parser.add_argument("--no-chart", action="store_true", help="不生成/不打开图表（CI 或快速跑建议开）")
    parser.add_argument("--skip-step1", action="store_true", help="跳过 step1 数据准备（要求本地已有缓存）")
    parser.add_argument("--skip-step2", action="store_true", help="跳过 step2 因子计算（要求本地已有缓存）")
    parser.add_argument("--skip-step3", action="store_true", help="跳过 step3 选币（要求本地已有选币结果缓存）")
    args = parser.parse_args()

    print("========================================")
    print("     1号择时策略 - 接口版回测入口       ")
    print("========================================")

    conf = load_config()
    conf.info()

    脑子 = 一号择时策略脑子(conf)
    选币结果 = 脑子.生成选币结果(
        参数=一号择时脑子运行参数(
            跳过数据准备=bool(args.skip_step1),
            跳过因子计算=bool(args.skip_step2),
            跳过选币=bool(args.skip_step3),
        )
    )

    报告 = simulate_performance(conf, 选币结果, show_plot=not args.no_chart)

    if 报告 is not None:
        print("\n=== 回测报告（核心指标） ===")
        print(报告)


if __name__ == "__main__":
    main()

