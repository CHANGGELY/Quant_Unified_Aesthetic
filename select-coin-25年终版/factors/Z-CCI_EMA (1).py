import numpy as np
import pandas as pd


def signal(candle_df, param, *args):
    """
    因子名称: SmoothedCCI (平滑的商品通道指数)
    核心逻辑: 基于价格对移动平均和平均绝对偏差的乖离程度，并使用EMA进行平滑。
    空头用法: 升序 (True)。值越小（负值越极端），超买越严重，空头信号越强。

    :param candle_df: 单个币种的K线数据 (DataFrame)
    :param param: CCI 计算周期 n (例如 20)
    :param args: args[0] 为因子名称
    """
    n = param
    factor_name = args[0]

    # 1. 计算典型价格 (TP)
    # TP = (High + Low + Close) / 3
    tp = (candle_df['high'] + candle_df['low'] + candle_df['close']) / 3

    # 2. 计算 TP 的移动平均 (MA)
    ma_tp = tp.rolling(window=n, min_periods=1).mean()

    # 3. 计算平均绝对偏差 (MD) - **注意：此处沿用您代码中的计算逻辑**
    # MD = mean(|TP - MA(TP, n)|)
    abs_diff = abs(tp - ma_tp)
    md = abs_diff.rolling(window=n, min_periods=1).mean()

    # 4. 计算原始 CCI
    # CCI = (TP - MA) / (0.015 * MD)

    # 增强健壮性：处理除零 (MD 为 0 时)
    safe_md = md * 0.015
    # 使用 np.where 避免除零，并在分母为零时返回 0 或 NaN
    cci_raw = np.where(safe_md != 0, (tp - ma_tp) / safe_md, 0)

    # 转换为 Pandas Series 以便进行 EMA 运算
    cci_raw = pd.Series(cci_raw, index=candle_df.index)

    # 5. EMA 平滑 (保持您代码中的 span=5 的设置)
    # 这是您认为效果更好的关键步骤
    smoothed_cci = cci_raw.ewm(span=5, adjust=False, min_periods=1).mean()

    # 6. 赋值并返回
    candle_df[factor_name] = smoothed_cci

    # (无需 del 操作，因为 TP, MA, MD 都是局部变量)
    return candle_df