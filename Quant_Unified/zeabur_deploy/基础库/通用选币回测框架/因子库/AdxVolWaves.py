import numpy as np
import pandas as pd
from .TMV import calculate_adx


def signal(candle_df, param, *args):
    factor_name = args[0] if args else "AdxVolWaves"

    if isinstance(param, tuple):
        bb_length = param[0] if len(param) > 0 else 20
        bb_mult = param[1] if len(param) > 1 else 1.5
        adx_length = param[2] if len(param) > 2 else 14
        adx_influence = param[3] if len(param) > 3 else 0.8
        zone_offset = param[4] if len(param) > 4 else 1.0
        zone_expansion = param[5] if len(param) > 5 else 1.0
        smooth_length = param[6] if len(param) > 6 else 50
        signal_cooldown = param[7] if len(param) > 7 else 20
    else:
        bb_length = int(param)
        bb_mult = 1.5
        adx_length = 14
        adx_influence = 0.8
        zone_offset = 1.0
        zone_expansion = 1.0
        smooth_length = 50
        signal_cooldown = 20

    close = candle_df["close"]
    high = candle_df["high"]
    low = candle_df["low"]

    adx_df = calculate_adx(candle_df, adx_length)
    adx = adx_df["adx"]
    di_plus = adx_df["di_plus"]
    di_minus = adx_df["di_minus"]
    adx_normalized = adx / 100.0

    bb_basis = close.rolling(window=bb_length, min_periods=1).mean()
    bb_dev = close.rolling(window=bb_length, min_periods=1).std()

    adx_multiplier = 1.0 + adx_normalized * adx_influence
    bb_dev_adjusted = bb_mult * bb_dev * adx_multiplier

    bb_upper = bb_basis + bb_dev_adjusted
    bb_lower = bb_basis - bb_dev_adjusted

    bb_basis_safe = bb_basis.replace(0, np.nan)
    bb_width = (bb_upper - bb_lower) / bb_basis_safe * 100.0
    bb_width = bb_width.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    bb_upper_smooth = bb_upper.rolling(window=smooth_length, min_periods=1).mean()
    bb_lower_smooth = bb_lower.rolling(window=smooth_length, min_periods=1).mean()
    bb_range_smooth = bb_upper_smooth - bb_lower_smooth

    offset_distance = bb_range_smooth * zone_offset

    top_zone_bottom = bb_upper_smooth + offset_distance
    top_zone_top = top_zone_bottom + bb_range_smooth * zone_expansion

    bottom_zone_top = bb_lower_smooth - offset_distance
    bottom_zone_bottom = bottom_zone_top - bb_range_smooth * zone_expansion

    price_in_top_zone = close > top_zone_bottom
    price_in_bottom_zone = close < bottom_zone_top

    bb_width_ma = bb_width.rolling(window=50, min_periods=1).mean()
    is_squeeze = bb_width < bb_width_ma

    price_in_top_zone_prev = price_in_top_zone.shift(1).fillna(False)
    price_in_bottom_zone_prev = price_in_bottom_zone.shift(1).fillna(False)

    n = len(candle_df)
    enter_top = np.zeros(n, dtype=bool)
    enter_bottom = np.zeros(n, dtype=bool)

    top_vals = price_in_top_zone.to_numpy()
    bottom_vals = price_in_bottom_zone.to_numpy()
    top_prev_vals = price_in_top_zone_prev.to_numpy()
    bottom_prev_vals = price_in_bottom_zone_prev.to_numpy()

    last_buy_bar = -10**9
    last_sell_bar = -10**9

    for i in range(n):
        if top_vals[i] and (not top_prev_vals[i]) and (i - last_sell_bar >= signal_cooldown):
            enter_top[i] = True
            last_sell_bar = i
        if bottom_vals[i] and (not bottom_prev_vals[i]) and (i - last_buy_bar >= signal_cooldown):
            enter_bottom[i] = True
            last_buy_bar = i

    factor_main = np.where(enter_bottom, 1.0, 0.0)
    factor_main = np.where(enter_top, -1.0, factor_main)

    candle_df[factor_name] = factor_main
    candle_df[f"{factor_name}_ADX"] = adx
    candle_df[f"{factor_name}_DI_Plus"] = di_plus
    candle_df[f"{factor_name}_DI_Minus"] = di_minus
    candle_df[f"{factor_name}_BB_Upper"] = bb_upper
    candle_df[f"{factor_name}_BB_Lower"] = bb_lower
    candle_df[f"{factor_name}_TopZoneBottom"] = top_zone_bottom
    candle_df[f"{factor_name}_BottomZoneTop"] = bottom_zone_top
    candle_df[f"{factor_name}_Squeeze"] = is_squeeze.astype(int)
    candle_df[f"{factor_name}_EnterTop"] = enter_top.astype(int)
    candle_df[f"{factor_name}_EnterBottom"] = enter_bottom.astype(int)

    return candle_df

