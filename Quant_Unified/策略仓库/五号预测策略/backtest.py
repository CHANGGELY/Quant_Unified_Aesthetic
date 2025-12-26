from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix

# 将 Quant_Unified 和关键目录加入搜索路径（与其他策略保持一致）
QUANT_ROOT = Path(__file__).resolve().parents[2]
if str(QUANT_ROOT) not in sys.path:
    sys.path.append(str(QUANT_ROOT))

for folder in ["基础库", "服务", "策略仓库", "应用"]:
    p = QUANT_ROOT / folder
    if p.exists() and str(p) not in sys.path:
        sys.path.append(str(p))

from common_core.backtest.signal import positions_from_probs_hysteresis  # noqa: E402

from 策略仓库.五号预测策略.config_backtest import PredictStrategy5Config  # noqa: E402
from 策略仓库.五号预测策略.program.step1_prepare_data import load_resampled_1s  # noqa: E402
from 策略仓库.五号预测策略.program.step2_build_dataset import build_features_1s, make_dataset_from_features  # noqa: E402
from 策略仓库.五号预测策略.program.step3_train_calibrate import (  # noqa: E402
    save_artifacts,
    time_split,
    top_feature_importance,
    train_and_calibrate,
)
from 策略仓库.五号预测策略.program.step4_simulate import simulate_always_in  # noqa: E402


def _precision_for_threshold(y_true: np.ndarray, p: np.ndarray, target_label: int, p_th: float) -> float | None:
    mask = p >= p_th
    if mask.sum() == 0:
        return None
    return float((y_true[mask] == target_label).mean())


def run_once(
    cfg: PredictStrategy5Config,
    feat: pd.DataFrame,
    horizon_s: int,
    label_mode: str,
    feature_cols: list[str],
    save_model: bool = False,
) -> dict:
    X, y, meta = make_dataset_from_features(
        feat, horizon_s=horizon_s, threshold=cfg.label_threshold, mode=label_mode, feature_cols=feature_cols
    )
    X_train, y_train, X_cal, y_cal, X_test, y_test = time_split(X, y, cfg.train_frac, cfg.calib_frac)

    art = train_and_calibrate(
        X_train=X_train,
        y_train=y_train,
        X_cal=X_cal,
        y_cal=y_cal,
        calib_method=cfg.calib_method,
        random_state=cfg.random_state,
    )

    if save_model:
        model_path = Path("models") / f"{cfg.symbol}_{label_mode}_h{horizon_s}.pkl"
        model_path.parent.mkdir(parents=True, exist_ok=True)
        save_artifacts(art, model_path)
        print(f"Model saved to: {model_path}")
    imp = top_feature_importance(art, top_n=12)

    proba = art.calibrated_model.predict_proba(X_test)
    y_pred = np.asarray(np.argmax(proba, axis=1), dtype=int)
    y_true = y_test.to_numpy(dtype=int)

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1, 2])

    p_down = proba[:, 0]
    p_up = proba[:, 2]
    buy_prec = _precision_for_threshold(y_true, p_up, target_label=2, p_th=cfg.p_enter)
    sell_prec = _precision_for_threshold(y_true, p_down, target_label=0, p_th=cfg.p_enter)

    pos = positions_from_probs_hysteresis(
        p_up=p_up.astype(np.float64),
        p_down=p_down.astype(np.float64),
        p_enter=float(cfg.p_enter),
        p_exit=float(cfg.p_exit),
        diff_enter=float(cfg.diff_enter),
        diff_exit=float(cfg.diff_exit),
        init_pos=0,
    )

    meta_test = meta.loc[X_test.index]
    sim = simulate_always_in(
        meta_test,
        pos,
        fee_rate=cfg.fee_rate,
        slippage_rate=cfg.slippage_rate,
        qty_step=cfg.qty_step,
        leverage=cfg.leverage,
        initial_capital=cfg.initial_capital,
        min_order_notional=cfg.min_order_notional,
    )

    net = sim.equity / cfg.initial_capital
    dd = net / net.cummax() - 1.0
    total_return = float(net.iloc[-1] - 1.0)
    max_dd = float(dd.min())
    n_trades = int((sim.turnover > 0).sum())
    total_cost = float(sim.cost.sum())
    total_turnover = float(sim.turnover.sum())

    def _fmt(v: float | None) -> str:
        return "NA" if v is None else f"{v:.3f}"

    print(
        f"[Run] h={horizon_s:>2d}s mode={label_mode:<10s} "
        f"trades={n_trades:>4d} rtn={total_return*100:>7.2f}% dd={max_dd*100:>7.2f}% "
        f"prec_buy={_fmt(buy_prec)} prec_sell={_fmt(sell_prec)}"
    )

    return {
        "symbol": cfg.symbol,
        "horizon_s": horizon_s,
        "label_mode": label_mode,
        "model": art.model_name,
        "calib_method": cfg.calib_method,
        "train_size": len(X_train),
        "calib_size": len(X_cal),
        "test_size": len(X_test),
        "test_bars": len(sim.equity),
        "trades": n_trades,
        "return": total_return,
        "max_dd": max_dd,
        "turnover": total_turnover,
        "cost": total_cost,
        "buy_prec@p_enter": buy_prec,
        "sell_prec@p_enter": sell_prec,
        "cm_true_down": int(cm[0].sum()),
        "cm_true_hold": int(cm[1].sum()),
        "cm_true_up": int(cm[2].sum()),
        "top_features": ", ".join([n for n, _ in imp[:8]]),
    }


def main() -> None:
    cfg = PredictStrategy5Config()
    symbol_dir = cfg.data_root / cfg.symbol
    day_dirs = sorted([p for p in symbol_dir.iterdir() if p.is_dir()]) if symbol_dir.exists() else []
    df_1s, used_days = load_resampled_1s(
        cfg.data_root,
        cfg.symbol,
        depth_levels=getattr(cfg, "depth_levels", 5),
        start_date=getattr(cfg, "start_date", None),
        end_date=getattr(cfg, "end_date", None),
        max_days=getattr(cfg, "max_days", None),
        cache_1s=getattr(cfg, "cache_1s", True),
        prefer_longest_contiguous=getattr(cfg, "prefer_longest_contiguous", True),
    )
    feat, feature_names = build_features_1s(df_1s)

    if used_days:
        print(
            f"Loaded {cfg.symbol}: used_days={len(used_days)} ({used_days[0].name}..{used_days[-1].name}), "
            f"1s_bars={len(df_1s):,}"
        )
    elif day_dirs:
        print(f"Loaded {cfg.symbol}: days={len(day_dirs)}, 1s_bars={len(df_1s):,}")
    else:
        print(f"Loaded {cfg.symbol}: 1s_bars={len(df_1s):,}")

    results = []
    for horizon_s in [5, 10, 20, 30, 60]:
        for mode in ["executable", "wmp"]:
            results.append(run_once(
                cfg, 
                feat=feat, 
                horizon_s=horizon_s, 
                label_mode=mode, 
                feature_cols=feature_names,
                save_model=True
            ))

    df = pd.DataFrame(results)
    if not df.empty:
        show_cols = [
            "symbol",
            "horizon_s",
            "label_mode",
            "trades",
            "return",
            "max_dd",
            "cost",
            "buy_prec@p_enter",
            "sell_prec@p_enter",
            "top_features",
        ]
        df_show = df[show_cols].copy()
        df_show["return"] = (df_show["return"] * 100).round(3)
        df_show["max_dd"] = (df_show["max_dd"] * 100).round(3)
        df_show["cost"] = df_show["cost"].round(2)
        print("\n[Summary] return/max_dd 单位: %")
        print(df_show.sort_values(["return", "max_dd"], ascending=[False, True]).to_string(index=False))


if __name__ == "__main__":
    main()
