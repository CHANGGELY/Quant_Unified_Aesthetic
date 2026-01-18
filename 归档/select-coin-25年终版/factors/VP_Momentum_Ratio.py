import numpy as np
import pandas as pd


def signal(*args):
    df = args[0]
    # 三个周期参数：计数周期、成交量参考周期、涨跌幅参考周期
    n_count = args[1][0]  # K线计数滚动周期
    n_volume = args[1][1]  # 参考平均成交量周期
    n_change = args[1][2]  # 参考平均涨跌幅周期
    factor_name = args[2]

    # 确保数据列存在
    required_cols = ['open', 'close', 'high', 'low', 'volume']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"缺少必要列: {col}")

    # 1. 计算基础得分（上涨1，下跌-1，平盘0）
    df['base_score'] = np.where(
        df['close'] > df['open'], 1,
        np.where(df['close'] < df['open'], -1, 0)
    )

    # 2. 计算涨跌幅（绝对值）
    df['price_change_pct'] = np.abs(df['close'] - df['open']) / df['open']

    # 3. 计算参考平均值
    df['avg_volume'] = df['volume'].rolling(window=n_volume, min_periods=1).mean()
    df['avg_change'] = df['price_change_pct'].rolling(window=n_change, min_periods=1).mean()

    # 4. 计算成交量乘数（高于平均则乘2）
    volume_multiplier = np.where(df['volume'] > df['avg_volume'], 2, 1)

    # 5. 计算涨跌幅乘数（高于平均则乘2）
    change_multiplier = np.where(df['price_change_pct'] > df['avg_change'], 2, 1)

    # 6. 计算最终单根K线得分（绝对值最大为4）
    df['final_score'] = df['base_score'] * volume_multiplier * change_multiplier
    # 确保绝对值不超过4
    df['final_score'] = np.clip(df['final_score'], -4, 4)

    # 7. 在计数周期内计算正负数和比值
    def calculate_ratio(series):
        positive_sum = series[series > 0].sum()
        negative_abs_sum = np.abs(series[series < 0]).sum()
        total = positive_sum + negative_abs_sum

        if total == 0:
            return 0.5  # 如果正负都为0，返回中性值0.5
        else:
            return positive_sum / total

    # 滚动计算比值因子
    df[factor_name] = df['final_score'].rolling(
        window=n_count, min_periods=1
    ).apply(calculate_ratio, raw=False)

    # 清理中间列
    intermediate_cols = ['base_score', 'price_change_pct', 'avg_volume',
                         'avg_change', 'final_score']
    df.drop(intermediate_cols, axis=1, inplace=True, errors='ignore')

    return df