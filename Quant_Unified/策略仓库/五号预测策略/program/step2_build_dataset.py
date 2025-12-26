from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_COLS: list[str] = [
    "obi_l1",
    "obi_l5",
    "obi_decay",
    "ret_std_10",
    "hl_range_10",
    "dev_ma_60",
    "rsi_14",
    "spread",
]

META_COLS: list[str] = ["wmp", "bid1_p", "ask1_p", "mid", "spread"]


def _weighted_mid_price(df: pd.DataFrame) -> pd.Series:
    denom = (df["bid1_q"] + df["ask1_q"]).replace(0, np.nan)
    w_bid = df["bid1_q"] / denom
    w_ask = df["ask1_q"] / denom
    return df["ask1_p"] * w_bid + df["bid1_p"] * w_ask


def _rsi(price: pd.Series, window: int = 14) -> pd.Series:
    delta = price.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(window).mean()
    avg_loss = loss.rolling(window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def build_features_1s(df_1s: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    # 避免对全量 DataFrame 做 copy（容易 OOM）
    out = pd.DataFrame(index=df_1s.index)
    
    current_features = []

    bid1_p = df_1s["bid1_p"]
    ask1_p = df_1s["ask1_p"]
    bid1_q = df_1s["bid1_q"].fillna(0.0)
    ask1_q = df_1s["ask1_q"].fillna(0.0)

    out["spread"] = ask1_p - bid1_p
    out["mid"] = (ask1_p + bid1_p) / 2.0
    denom = (bid1_q + ask1_q).replace(0, np.nan)
    out["wmp"] = ask1_p * (bid1_q / denom) + bid1_p * (ask1_q / denom)
    
    current_features.append("spread")

    # OBI L1
    l1_denom = (bid1_q + ask1_q).replace(0, np.nan)
    out["obi_l1"] = (bid1_q - ask1_q) / l1_denom
    current_features.append("obi_l1")

    # Deep OBI (L5, L10, L20, L50)
    for level in [5, 10, 20, 50]:
        bid_cols = [f"bid{i}_q" for i in range(1, level + 1)]
        ask_cols = [f"ask{i}_q" for i in range(1, level + 1)]
        
        # 确保列存在
        bid_cols = [c for c in bid_cols if c in df_1s.columns]
        ask_cols = [c for c in ask_cols if c in df_1s.columns]
        
        if not bid_cols or not ask_cols:
            continue
            
        bid_q = df_1s.reindex(columns=bid_cols).fillna(0.0)
        ask_q = df_1s.reindex(columns=ask_cols).fillna(0.0)
        
        bid_sum = bid_q.sum(axis=1)
        ask_sum = ask_q.sum(axis=1)
        
        l_denom = (bid_sum + ask_sum).replace(0, np.nan)
        out[f"obi_l{level}"] = (bid_sum - ask_sum) / l_denom
        current_features.append(f"obi_l{level}")

        # Decay OBI for L5 only (as legacy feature)
        if level == 5:
            weights = np.array([1.0, 0.8, 0.6, 0.4, 0.2])[:len(bid_cols)] # 适配实际列数
            bid_mat = bid_q.to_numpy(dtype=float)
            ask_mat = ask_q.to_numpy(dtype=float)
            bid_decay = (bid_mat * weights).sum(axis=1)
            ask_decay = (ask_mat * weights).sum(axis=1)
            denom_decay = (bid_decay + ask_decay)
            denom_decay = np.where(denom_decay == 0.0, np.nan, denom_decay)
            out["obi_decay"] = (bid_decay - ask_decay) / denom_decay
            current_features.append("obi_decay")

    # OFI（按秒聚合的成交）- 仅当 Trade 存在时计算
    if "buy_qty" in df_1s.columns:
        buy_qty = df_1s.get("buy_qty", 0.0)
        sell_qty = df_1s.get("sell_qty", 0.0)
        buy_notional = df_1s.get("buy_notional", 0.0)
        sell_notional = df_1s.get("sell_notional", 0.0)

        out["ofi_1s"] = buy_qty - sell_qty
        out["ofi_notional_1s"] = buy_notional - sell_notional
        out["ofi_5s"] = out["ofi_1s"].rolling(5).sum()
        out["buy_notional_5s"] = buy_notional.rolling(5).sum() if hasattr(buy_notional, "rolling") else 0.0
        
        current_features.extend(["ofi_1s", "ofi_5s", "ofi_notional_1s", "buy_notional_5s"])

    # 波动率
    ret = out["wmp"].pct_change()
    out["ret_std_10"] = ret.rolling(10).std()
    roll_max = out["wmp"].rolling(10).max()
    roll_min = out["wmp"].rolling(10).min()
    out["hl_range_10"] = (roll_max - roll_min) / out["wmp"]
    current_features.extend(["ret_std_10", "hl_range_10"])

    # 动量 / 反转
    ma_60 = out["wmp"].rolling(60).mean()
    out["dev_ma_60"] = (out["wmp"] - ma_60) / ma_60
    out["rsi_14"] = _rsi(out["wmp"], window=14)
    current_features.extend(["dev_ma_60", "rsi_14"])
    
    out["bid1_p"] = bid1_p
    out["ask1_p"] = ask1_p
    return out, current_features


def build_label(df_feat: pd.DataFrame, horizon_s: int, threshold: float, mode: str) -> pd.Series:
    """
    返回 multiclass 标签：0=Down, 1=Hold, 2=Up
    """
    if horizon_s <= 0:
        raise ValueError("horizon_s must be > 0")
    if threshold <= 0:
        raise ValueError("threshold must be > 0")

    if mode == "wmp":
        future = df_feat["wmp"].shift(-horizon_s)
        r = future / df_feat["wmp"] - 1.0
        up = r >= threshold
        down = r <= -threshold
    elif mode == "executable":
        future_bid = df_feat["bid1_p"].shift(-horizon_s)
        future_ask = df_feat["ask1_p"].shift(-horizon_s)

        long_r = future_bid / df_feat["ask1_p"] - 1.0  # 买入跨点差，未来卖出 bid
        short_r = future_ask / df_feat["bid1_p"] - 1.0  # 卖出跨点差，未来买回 ask（通常为负）
        up = long_r >= threshold
        down = short_r <= -threshold
    else:
        raise ValueError(f"unknown label mode: {mode}")

    y = pd.Series(np.int8(1), index=df_feat.index)  # Hold
    y.loc[down] = np.int8(0)
    y.loc[up] = np.int8(2)
    return y


def make_dataset(
    df_1s: pd.DataFrame, horizon_s: int, threshold: float, mode: str
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    feat, feature_names = build_features_1s(df_1s)
    return make_dataset_from_features(feat, horizon_s=horizon_s, threshold=threshold, mode=mode, feature_cols=feature_names)


def make_dataset_from_features(
    feat: pd.DataFrame, horizon_s: int, threshold: float, mode: str, feature_cols: list[str] | None = None
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    y = build_label(feat, horizon_s=horizon_s, threshold=threshold, mode=mode)
    
    if feature_cols is None:
        # 自动推断：排除 META_COLS 和 label 相关的列
        feature_cols = [c for c in feat.columns if c not in META_COLS]
        # 再次过滤，确保只包含 FEATURE_COLS 中定义的（如果有）或者全部
        # 这里为了兼容动态特征，直接使用所有非 Meta 列作为特征
        
    # 确保特征列存在
    valid_cols = [c for c in feature_cols if c in feat.columns]
    X = feat[valid_cols]
    
    df_all = X.join(y.rename("y"), how="inner").dropna()
    meta = feat.loc[df_all.index, META_COLS].copy()
    return df_all[valid_cols].copy(), df_all["y"].astype("int64"), meta
