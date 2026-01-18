# -*- coding: utf-8 -*-
"""
CciBiasRatioStd 因子（时间序列）
基于 CCI Bias 比例型因子的 n 期标准差衡量 CCI 波动强度
author: 邢不行框架适配
"""
def signal(*args):
    df = args[0]
    n = args[1]            # CCI计算窗口 & 波动率计算窗口
    factor_name = args[2]

    # 1) 按 CCI 因子模板计算 CCI 值 
    df['tp'] = (df['high'] + df['low'] + df['close']) / 3
    df['ma'] = df['tp'].rolling(window=n, min_periods=1).mean()
    df['md'] = abs(df['tp'] - df['ma']).rolling(window=n, min_periods=1).mean()
    df['cci_tmp'] = (df['tp'] - df['ma']) / df['md'] / 0.015

    # 2) 计算 CCI 的 n 期滚动均值，作为基准水平
    df['cci_ma'] = df['cci_tmp'].rolling(window=n, min_periods=1).mean()

    # 3) 比例型偏离： (CCI - 均值) / 均值
    # 注意：若 cci_ma 接近 0，可能产生极大值:contentReference[oaicite:8]{index=8}
    df['cci_bias_ratio'] = (df['cci_tmp'] - df['cci_ma']) / df['cci_ma']

    # 4) 计算比例偏离序列在 n 周期的标准差作为波动强度因子
    df[factor_name] = df['cci_bias_ratio'].rolling(window=n, min_periods=1).std()

    # 5) 清理临时字段
    del df['tp'], df['ma'], df['md'], df['cci_tmp'], df['cci_ma'], df['cci_bias_ratio']

    return df
