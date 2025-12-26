# -*- coding: utf-8 -*-
"""
Rejection_Max 因子 (Maximum Price Rejection Filter)
===================================================
作者: Gemini (Based on User Idea)
类型: 风控/过滤因子

功能说明：
检测过去 N 周期内，是否存在“日内价格回撤幅度”极大的情况。
旨在过滤掉那些经历过“插针”、“天地针”或“单日大暴跌”的高风险币种。

计算逻辑：
1. 计算单根 K 线的日内高点偏离度：Ratio = (High / Close) - 1
2. 获取该比率在 N 周期内的最大值：Max_Ratio = Rolling_Max(Ratio, N)
3. 阈值判断：
   - 如果 Max_Ratio > 0.3 (即当日最高价比收盘价高出 30% 以上)，返回 1。
   - 否则返回 0。

参数：
- n: 滚动窗口周期数（例如 20）

使用示例：
- ('Rejection_Max', 20, 'val:==0')
  含义：只选择过去 20 天内没有出现过单日 30% 以上巨幅回撤的币种。
"""

import pandas as pd
import numpy as np


def signal(candle_df, param, *args):
    """
    Rejection_Max 因子计算函数
    :param candle_df: 单个币种的K线数据
    :param param: int, 滚动窗口周期数 n
    :param args: tuple, args[0] 为因子列名
    :return: candle_df
    """
    n = int(param)
    factor_name = args[0]

    # 阈值设定 (硬编码为 30%，也可根据需要改为参数传入)
    THRESHOLD = 0.3

    # --- 1. 计算日内高点回撤比率 (High-Close Deviation) ---
    # 公式：(最高价 / 收盘价) - 1
    # 含义：如果 High=130, Close=100, 结果为 0.3。代表收盘价较最高价回落了相当大的比例。
    deviation_ratio = (candle_df['high'] / candle_df['close']) - 1

    # --- 2. 获取滚动窗口内的最大风险值 ---
    # 只要过去 N 天内出现过一次巨大的回撤，该窗口期的值就会变大
    rolling_max_deviation = deviation_ratio.rolling(window=n, min_periods=1).max()

    # --- 3. 生成信号 ---
    # 判断最大回撤比率是否超过阈值 (0.3)
    # 超过则标记为 1 (危险)，否则为 0 (安全)
    condition = rolling_max_deviation > THRESHOLD

    # 转换为整型
    candle_df[factor_name] = condition.astype(int)

    return candle_df