# -*- coding: utf-8 -*-
"""
CciBias 比例型因子（时间序列）
基于 CCI 相对自身近期均值的比例偏离
author: 邢不行框架适配
"""

def signal(*args):
    df = args[0]
    n = args[1]          # CCI 计算窗口 & Bias 平滑窗口
    factor_name = args[2]

    # 1) 按 Cci 因子模板计算 CCI
    df['tp'] = (df['high'] + df['low'] + df['close']) / 3
    df['ma'] = df['tp'].rolling(window=n, min_periods=1).mean()
    df['md'] = abs(df['tp'] - df['ma']).rolling(window=n, min_periods=1).mean()
    df['cci_tmp'] = (df['tp'] - df['ma']) / df['md'] / 0.015

    # 2) 计算 CCI 的 n 期滚动均值，作为基准
    df['cci_ma'] = df['cci_tmp'].rolling(window=n, min_periods=1).mean()

    # 3) 比例型 CciBias： (CCI - 均值) / 均值
    # 注意：若 cci_ma 接近 0，可能产生较大数值，可在回测中视情况做截断处理
    df[factor_name] = (df['cci_tmp'] - df['cci_ma']) / df['cci_ma']

    # 4) 清理临时字段
    del df['tp']
    del df['ma']
    del df['md']
    del df['cci_tmp']
    del df['cci_ma']

    return df


def signal_multi_params(df, param_list) -> dict:
    """
    多参数计算版本
    """
    ret = dict()
    for param in param_list:
        n = int(param)

        # 1) 计算 CCI
        tp = (df['high'] + df['low'] + df['close']) / 3
        ma = tp.rolling(window=n, min_periods=1).mean()
        md = abs(tp - ma).rolling(window=n, min_periods=1).mean()
        cci = (tp - ma) / md / 0.015

        # 2) CCI 的 n 期滚动均值
        cci_ma = cci.rolling(window=n, min_periods=1).mean()

        # 3) 比例型 CciBias
        ret[str(param)] = (cci - cci_ma) / cci_ma

    return ret
