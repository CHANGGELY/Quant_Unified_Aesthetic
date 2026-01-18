# -*- coding: utf-8 -*-
"""
一号择时策略 - 策略脑子（“脑子 + 执行器”架构版）

这个文件是干嘛的？
    一号择时策略不是那种“挂一堆限价单等成交”的策略，它更像“基金经理”：
        - 先看一堆币的指标（因子）
        - 再挑出要买/要卖的币（选币）
        - 最后给出“每个币应该占我总资金的多少比例”（目标权重）

为了让它也能和其它策略一样，符合统一架构：
    - 脑子：只负责输出“目标权重表”（选币结果）
    - 执行器：负责把目标权重变成真实交易（回测里模拟调仓，实盘里下真实单）

你可以把它理解成：
    - 脑子负责“出作业答案”
    - 执行器负责“按答案去做题，并检查有没有爆仓（保证金不够）”
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.model.backtest_config import BacktestConfig
from program.step1_prepare_data import prepare_data
from program.step2_calculate_factors import calc_factors
from program.step3_select_coins import aggregate_select_results, select_coins


@dataclass(slots=True)
class 一号择时脑子运行参数:
    """
    控制“一号择时策略脑子”运行哪些步骤。

    为什么需要它？
        这套策略的前 3 步（准备数据/算因子/选币）可能很耗时，
        有了这些开关，你就能：
            - 首次跑：全开
            - 以后调参：跳过已缓存的步骤，只重跑必要部分
    """

    跳过数据准备: bool = False
    跳过因子计算: bool = False
    跳过选币: bool = False


class 一号择时策略脑子:
    """
    一号择时策略脑子（接口包装器）

    输出：
        - 选币结果（DataFrame），包含每个周期挑选出的币种与目标权重（target_alloc_ratio）
    """

    策略名称 = "1号择时策略"

    def __init__(self, conf: BacktestConfig) -> None:
        if conf is None:
            raise ValueError("conf 不能为空")
        self._conf = conf

    def 生成选币结果(self, *, 参数: 一号择时脑子运行参数 | None = None) -> pd.DataFrame:
        if 参数 is None:
            参数 = 一号择时脑子运行参数()

        if not 参数.跳过数据准备:
            prepare_data(self._conf)

        if not 参数.跳过因子计算:
            calc_factors(self._conf)

        if not 参数.跳过选币:
            select_coins(self._conf)
            if self._conf.strategy_short is not None:
                select_coins(self._conf, is_short=True)

        return aggregate_select_results(self._conf)

