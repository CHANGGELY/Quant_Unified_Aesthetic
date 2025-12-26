# -*- coding: utf-8 -*-
"""
ATR 波动率因子（时间序列）
基于真实波幅的均值衡量价格波动率
author: 邢不行框架适配
"""
def signal(*args):
    df = args[0]
    n = args[1]            # ATR计算窗口
    factor_name = args[2]

    # 1) 计算 True Range (TR)
    df['pre_close'] = df['close'].shift(1)  # 前一周期收盘价
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = (df['high'] - df['pre_close']).abs()
    df['tr3'] = (df['low'] - df['pre_close']).abs()
    df['TR'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)  # 三者取最大:contentReference[oaicite:1]{index=1}

    # 2) 计算 ATR：TR 的 n 期滚动均值作为波动率指标
    df[factor_name] = df['TR'].rolling(window=n, min_periods=1).mean()

    # 3) 清理临时字段
    del df['pre_close'], df['tr1'], df['tr2'], df['tr3'], df['TR']

    return df
