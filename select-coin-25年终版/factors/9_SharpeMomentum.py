# -*- coding: utf-8 -*-
"""
多头动量因子9 | 夏普动量因子
author: D Luck
"""

import pandas as pd
import numpy as np

def signal(*args):
    df, n, factor_name = args

    ret = df['close'].pct_change()
    mean_ = ret.rolling(n, min_periods=1).mean()
    std_ = ret.rolling(n, min_periods=1).std()

    df[factor_name] = mean_ / (std_ + 1e-12)
    return df


def signal_multi_params(df, param_list) -> dict:
    ret_dic = {}
    ret = df['close'].pct_change()

    for param in param_list:
        n = int(param)

        mean_ = ret.rolling(n).mean()
        std_ = ret.rolling(n).std()

        ret_dic[str(param)] = mean_ / (std_ + 1e-12)

    return ret_dic
