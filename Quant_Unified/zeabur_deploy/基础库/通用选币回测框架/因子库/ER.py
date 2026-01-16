import pandas as pd
import numpy as np


def signal(candle_df, param, *args):
    """
    ER (Efficiency Ratio) 因子计算 - 标准数值版

    注意：此函数只计算 0~1 之间的 ER 数值。
    过滤逻辑（如 >=0.25）请在 config.py 的配置字符串中设置。
    """
    # 1. 获取框架生成的列名 (例如 'ER_20')
    factor_name = args[0] if len(args) > 0 else "ER"
    n = int(param)

    # 2. 计算 ER 核心数据
    # 分子：价格净位移
    change = (candle_df["close"] - candle_df["close"].shift(n)).abs()
    # 分母：价格总路径
    volatility = (candle_df["close"] - candle_df["close"].shift(1)).abs()
    path = volatility.rolling(window=n).sum()

    # 3. 计算 ER 值 (结果范围 0.0 ~ 1.0)
    # 处理分母为0的情况
    er = change / path
    er = er.replace([float("inf"), -float("inf")], 0).fillna(0)

    # 4. 直接将原始数值赋值给 DataFrame
    # 关键点：不要在这里做 >0.25 的判断，把数值给框架，框架会根据 config 自动过滤
    candle_df[factor_name] = er

    return candle_df
