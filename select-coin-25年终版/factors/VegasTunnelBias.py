"""
邢不行™️选币框架
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662

未经授权，不得复制、修改、或使用本代码的全部或部分内容。仅限个人学习用途，禁止商业用途。

Author: 邢不行
--------------------------------------------------------------------------------

# ** Vegas隧道乖离率因子 **
Vegas隧道乖离率因子基于EMA（指数移动平均线）构建，通过计算价格相对于特定EMA组合的偏离程度来识别趋势和超买超卖状态。

# ** 计算逻辑 **
1. 计算两条EMA线：EMA_short（短期EMA）和EMA_long（长期EMA）
2. 计算价格相对于EMA隧道的乖离率
3. 乖离率 = (收盘价 - EMA隧道中值) / EMA隧道中值 * 100

# ** 参数说明 **
- param: EMA周期参数，格式为"short_period,long_period"，例如"5,20"
"""

import pandas as pd
import numpy as np


def signal(*args):
    """
    计算Vegas隧道乖离率因子
    :param args: 参数列表
        args[0]: DataFrame，单个币种的K线数据
        args[1]: 参数，EMA周期配置，格式为"short_period,long_period"
        args[2]: 因子名称
    :return: 包含因子数据的DataFrame
    """
    df = args[0]
    param_str = args[1]
    factor_name = args[2]
    
    # 解析参数
    try:
        short_period, long_period = map(int, param_str.split(','))
    except:
        # 如果参数格式错误，使用默认值
        short_period, long_period = 5, 20
    
    # 计算短期EMA
    ema_short = df['close'].ewm(span=short_period, adjust=False).mean()
    
    # 计算长期EMA
    ema_long = df['close'].ewm(span=long_period, adjust=False).mean()
    
    # 计算EMA隧道中值（两条EMA的平均值）
    ema_tunnel_mid = (ema_short + ema_long) / 2
    
    # 计算乖离率：价格相对于EMA隧道中值的偏离程度
    df[factor_name] = (df['close'] - ema_tunnel_mid) / ema_tunnel_mid * 100
    
    return df


def signal_multi_params(df, param_list) -> dict:
    """
    多参数计算版本
    :param df: DataFrame，单个币种的K线数据
    :param param_list: 参数列表，每个参数为"short_period,long_period"格式
    :return: 包含不同参数下因子值的字典
    """
    ret = dict()
    
    for param in param_list:
        try:
            short_period, long_period = map(int, param.split(','))
            
            # 计算短期EMA
            ema_short = df['close'].ewm(span=short_period, adjust=False).mean()
            
            # 计算长期EMA
            ema_long = df['close'].ewm(span=long_period, adjust=False).mean()
            
            # 计算EMA隧道中值
            ema_tunnel_mid = (ema_short + ema_long) / 2
            
            # 计算乖离率
            ret[str(param)] = (df['close'] - ema_tunnel_mid) / ema_tunnel_mid * 100
            
        except Exception as e:
            print(f"参数 {param} 解析错误: {e}")
            continue
    
    return ret