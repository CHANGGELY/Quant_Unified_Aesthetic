import numpy as np


def _amount_series(df):
    if "quote_volume" in df.columns and df["quote_volume"].notna().any():
        return df["quote_volume"]
    return df["close"] * df["volume"]


def _parse_param(param):
    if isinstance(param, (list, tuple)) and len(param) >= 3:
        n_size = int(param[0])
        n_amount = int(param[1])
        n_mom = int(param[2])
        return n_size, n_amount, n_mom
    n = int(param)
    return n, n, n


def _calc_undergrad_factor(df, n_size: int, n_amount: int, n_mom: int):
    amount = _amount_series(df)

    size_score = np.log1p(amount.rolling(window=n_size, min_periods=1).mean().clip(lower=0))
    amount_score = np.log1p(amount.rolling(window=n_amount, min_periods=1).mean().clip(lower=0))

    mom_raw = df["close"].pct_change(n_mom)
    mom_score = np.log1p(mom_raw.abs().fillna(0))

    return (size_score + amount_score + mom_score).replace([np.inf, -np.inf], np.nan)


def signal(candle_df, param, *args):
    factor_name = args[0]
    n_size, n_amount, n_mom = _parse_param(param)
    candle_df[factor_name] = _calc_undergrad_factor(candle_df, n_size, n_amount, n_mom)
    return candle_df


def signal_multi_params(df, param_list) -> dict:
    ret = {}
    for param in param_list:
        n_size, n_amount, n_mom = _parse_param(param)
        ret[str(param)] = _calc_undergrad_factor(df, n_size, n_amount, n_mom)
    return ret

