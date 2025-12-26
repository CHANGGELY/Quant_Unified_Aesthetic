"""
邢不行™️选币框架
Python数字货币量化投资课程

版权所有 ©️ 邢不行
微信: xbx8662

未经授权，不得复制、修改、或使用本代码的全部或部分内容。仅限个人学习用途，禁止商业用途。

Author: 邢不行
--------------------------------------------------------------------------------

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
2          2023-11-24  1000BONK-USDT  0.004267  0.004335  0.003835  0.004140  17168514399  6.992947e+07     475254                   7940993618                  3.239266e+07     0.005917 2023-11-22 14:00:00         1
注意：若为小时级别策略，`candle_begin_time` 格式为 2023-11-22 14:00:00；若为日线，则为 2023-11-22。

# ** signal 参数示例 **
- 如果策略配置中 `factor_list` 包含 ('ILLIQ', True, 7, 1)，则 `param` 为 7，`args[0]` 为 'ILLIQ_7'。
- 如果策略配置中 `filter_list` 包含 ('ILLIQ', 7, 'pct:<0.8')，则 `param` 为 7，`args[0]` 为 'ILLIQ_7'。
"""

def signal(candle_df, param, *args):
    """
    计算ILLIQ流动性因子
    
    ILLIQ (Illiquidity) 因子衡量的是流动性溢价，基于价格路径的最短距离计算。
    该因子反映了市场流动性状况，流动性越差，ILLIQ值越大。
    
    计算逻辑：
    1. 计算盘中最短路径：min(开低高收路径, 开高低收路径)
    2. 计算隔夜波动路径：|开盘价 - 前收盘价|
    3. 最短路径 = 盘中最短路径 + 隔夜波动路径
    4. 标准化：最短路径 / 开盘价
    5. ILLIQ = 成交额 / 标准化最短路径
    6. 对ILLIQ进行n期移动平均
    
    :param args: 参数列表
        - args[0]: DataFrame，包含K线数据
        - args[1]: int，移动平均周期参数n
        - args[2]: str，因子列名
    :return: DataFrame，包含计算后的ILLIQ因子
    """
    n = param
    factor_name = args[0]

    # 计算盘中最短路径
    # 开低高收路径：(开盘价 - 最低价) + (最高价 - 最低价) + (最高价 - 收盘价)
    candle_df['开低高收'] = (candle_df['open'] - candle_df['low']) + (candle_df['high'] - candle_df['low']) + (candle_df['high'] - candle_df['close'])
    
    # 开高低收路径：(最高价 - 开盘价) + (最高价 - 最低价) + (收盘价 - 最低价)
    candle_df['开高低收'] = (candle_df['high'] - candle_df['open']) + (candle_df['high'] - candle_df['low']) + (candle_df['close'] - candle_df['low'])
    
    # 盘中最短路径取两者最小值
    candle_df['盘中最短路径'] = candle_df[['开低高收', '开高低收']].min(axis=1)
    
    # 计算隔夜波动路径：|开盘价 - 前收盘价|
    candle_df['隔夜波动路径'] = abs(candle_df['open'] - candle_df['close'].shift(1))
    
    # 最短路径 = 盘中最短路径 + 隔夜波动路径
    candle_df['最短路径'] = candle_df['盘中最短路径'] + candle_df['隔夜波动路径']
    
    # 消除价格对最短路径的影响：最短路径 / 开盘价
    candle_df['最短路径_标准化'] = candle_df['最短路径'] / candle_df['open']
    
    # 计算流动性溢价因子：成交额 / 标准化最短路径
    candle_df['ILLIQ'] = candle_df['quote_volume'] / candle_df['最短路径_标准化']
    
    # 对ILLIQ进行n期移动平均
    candle_df[factor_name] = candle_df['ILLIQ'].rolling(n, min_periods=1).mean()
    
    # 清理临时列
    candle_df.drop(columns=['开低高收', '开高低收', '盘中最短路径', '隔夜波动路径', '最短路径', '最短路径_标准化', 'ILLIQ'], inplace=True)

    return candle_df
