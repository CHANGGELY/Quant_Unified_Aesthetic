"""
邢不行™️选币框架
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662

未经授权，不得复制、修改、或使用本代码的全部或部分内容。仅限个人学习用途，禁止商业用途。

Author: 邢不行
--------------------------------------------------------------------------------

# ** 因子文件功能说明 **
1. Alpha006 (改良版): 量价相关性因子
2. 原版公式: -1 * Correlation(Open, Volume, n)
3. 币圈改良: Correlation(Open, Volume, n)
   - 去掉了 -1，为了更直观地判断趋势。
   - 值为正 (接近1): 价格与成交量正相关 (涨时放量，跌时缩量)，趋势真实。
   - 值为负 (接近-1): 价格与成交量负相关 (涨时缩量，跌时放量)，趋势虚假或背离。

"""

import numpy as np
import pandas as pd


def signal(candle_df, param, *args):
    """
    计算 Alpha006 因子
    :param candle_df: 单个币种的K线数据
    :param param: 计算相关系数的周期窗口 (例如 10 或 24)
    :param args: args[0] 为 factor_name
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0]  # 获取因子名称

    # 1. 提取数据
    # Alpha006 原始定义使用的是 Open 价格和 Volume
    # 逻辑：衡量一段时间内，开盘价的变化趋势是否得到了成交量的确认
    open_price = candle_df["open"]
    volume = candle_df["volume"]

    # 2. 计算滚动相关系数 (Rolling Correlation)
    # 使用 pandas 的 rolling().corr() 方法
    # param 是窗口长度 (window size)
    # min_periods=param//2 允许在数据初期只有一半数据时就开始计算，避免过多空值
    corr = open_price.rolling(window=param, min_periods=1).corr(volume)

    # 3. 赋值因子
    # 注意：这里没有乘以 -1。
    # 这样设置配合策略中的 "pct:>=0" 或 "val:>0" 过滤条件，
    # 可以筛选出"量价配合"健康的币种。
    candle_df[factor_name] = corr

    # 4. 处理极端值/空值 (可选，增强稳健性)
    # 将可能出现的无限值替换为NaN，随后填充0
    candle_df[factor_name] = candle_df[factor_name].replace([np.inf, -np.inf], np.nan)

    # 这里的 fillna(0) 是为了防止选币时因为前几行是 NaN 报错
    # 但实战中前几行通常会被 min_kline_num 过滤掉，所以不填也行，为了保险填个0
    # candle_df[factor_name] = candle_df[factor_name].fillna(0)

    return candle_df
