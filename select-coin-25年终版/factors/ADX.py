import numpy as np
import pandas as pd


def signal(*args):
    df = args[0].copy()  # 避免修改原数据
    N = args[1]
    factor_name = args[2]

    # 1. 计算 True Range (TR)
    prev_close = df['close'].shift(1)
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - prev_close).abs()
    tr3 = (df['low'] - prev_close).abs()
    df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # 2. 计算 +DM 和 -DM
    up_move = df['high'].diff()
    down_move = (-df['low'].diff())

    df['plus_dm'] = up_move.where((up_move > down_move) & (up_move > 0), 0)
    df['minus_dm'] = down_move.where((down_move > up_move) & (down_move > 0), 0)

    # 3. Wilders 平滑函数（关键！）
    def wilders_smooth(series, n):
        return series.ewm(alpha=1 / n, adjust=False).mean()

    df['tr_smooth'] = wilders_smooth(df['tr'], N)
    df['plus_dm_smooth'] = wilders_smooth(df['plus_dm'], N)
    df['minus_dm_smooth'] = wilders_smooth(df['minus_dm'], N)

    # 4. 计算 +DI 和 -DI
    df['plus_di'] = (df['plus_dm_smooth'] / df['tr_smooth']) * 100
    df['minus_di'] = (df['minus_dm_smooth'] / df['tr_smooth']) * 100

    # 5. 计算 DX
    di_sum = df['plus_di'] + df['minus_di']
    di_diff = (df['plus_di'] - df['minus_di']).abs()

    # 防止除零
    df['dx'] = np.where(di_sum > 0, (di_diff / di_sum) * 100, 0)

    # 6. ADX = DX 的 Wilders 平滑
    df['adx'] = wilders_smooth(df['dx'], N)

    # 7. 输出到指定列名
    df[factor_name] = df['adx']

    return df