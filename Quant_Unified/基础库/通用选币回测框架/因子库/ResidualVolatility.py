"""
选币策略框架 | 邢不行 | 2024分享会
作者: 邢不行
微信: xbx6660

# ** 因子文件功能说明 **
1. 因子库中的每个 Python 文件需实现 `signal` 函数，用于计算因子值。
2. 除 `signal` 外，可根据需求添加辅助函数，不影响因子计算逻辑。

# ** signal 函数参数与返回值说明 **
1. `signal` 函数的第一个参数为 `candle_df`，用于接收单个币种的 K 线数据。
2. `signal` 函数的第二个参数用于因子计算的主要参数，具体用法见函数实现。
3. `signal` 函数可以接收其他可选参数，按实际因子计算逻辑使用。
4. `signal` 函数的返回值应为包含因子数据的 K 线数据。

# ** candle_df 示例 **
    candle_begin_time         symbol      open      high       low     close       volume  quote_volume  trade_num  taker_buy_base_asset_volume  taker_buy_quote_asset_volume  funding_fee   first_candle_time  是否交易
0          2023-11-22  1000BONK-USDT  0.004780  0.004825  0.004076  0.004531  12700997933  5.636783e+07     320715                   6184933232                  2.746734e+07     0.001012 2023-11-22 14:00:00         1
1          2023-11-23  1000BONK-USDT  0.004531  0.004858  0.003930  0.004267  18971334686  8.158966e+07     573386                   8898242083                  3.831782e+07     0.001634 2023-11-22 14:00:00         1
2          2023-11-24  1000BONK-USDT  0.004267  0.004335  0.003835  0.004140  17168511399  6.992947e+07     475254                   7940993618                  3.239266e+07     0.005917 2023-11-22 14:00:00         1

# ** signal 参数示例 **
- 如果策略配置中 `factor_list` 包含 ('ResidualVolatility', True, 20, 1)，则 `param` 为 20，`args[0]` 为 'ResidualVolatility_20'。
- 如果策略配置中 `filter_list` 包含 ('ResidualVolatility', 20, 'pct:<0.8')，则 `param` 为 20，`args[0]` 为 'ResidualVolatility_20'。
"""


"""残差波动率因子，用于计算币种价格相对于趋势的波动性"""
import numpy as np
import pandas as pd


def signal(candle_df, param, *args):
    """
    计算残差波动率因子
    :param candle_df: 单个币种的K线数据
    :param param: 回看窗口长度，例如在 config 中配置 factor_list 为 ('ResidualVolatility', True, 20, 1)
    :param args: 其他可选参数，具体用法见函数实现
    :return: 包含因子数据的 K 线数据
    """
    factor_name = args[0]  # 从额外参数中获取因子名称

    # 对数价格
    period = param
    y = np.log(candle_df['close'])
    
    # 检查数据长度是否足够
    if len(y) < period:
        # 数据不足，返回全NaN的因子列
        candle_df[factor_name] = np.nan
        return candle_df
    
    windows = np.lib.stride_tricks.sliding_window_view(y, window_shape=period)
    x = np.arange(period)

    # 预计算固定值
    n = period
    sum_x = x.sum()
    sum_x2 = (x ** 2).sum()
    denominator = n * sum_x2 - sum_x ** 2
    
    # 滑动窗口统计量
    sum_y = windows.sum(axis=1)
    sum_xy = (windows * x).sum(axis=1)
    
    # 计算回归系数
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n
    
    # 计算预测值和残差
    y_pred = slope[:, None] * x + intercept[:, None]
    residuals = windows - y_pred
    
    # 计算残差的标准差作为波动率指标
    residual_volatility = np.std(residuals, axis=1, ddof=1)
    
    # 处理可能的NaN值
    residual_volatility = np.nan_to_num(residual_volatility, nan=0.0)
    
    # 对齐原始序列长度并添加到candle_df中
    full_volatility = pd.Series(index=candle_df.index, dtype=float)
    full_volatility.iloc[period-1:] = residual_volatility
    
    # 将因子添加到candle_df中
    candle_df[factor_name] = full_volatility
    
    return candle_df