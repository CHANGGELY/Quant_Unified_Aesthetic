from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


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
from 策略仓库.五号预测策略.program.step3_train_calibrate import TrainArtifacts, load_artifacts  # noqa: E402
from 策略仓库.五号预测策略.program.step4_simulate import simulate_always_in  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@dataclass(frozen=True)
class CrossSymbolResult:
    train_symbol: str
    test_symbol: str
    label_mode: str
    horizon_s: int
    bars: int
    trades: int
    return_pct: float
    max_dd_pct: float
    cost: float


def _load_models(model_dir: Path, train_symbol: str, label_mode: str, horizons_s: list[int]) -> dict[int, TrainArtifacts]:
    out: dict[int, TrainArtifacts] = {}
    for h in horizons_s:
        p = model_dir / f"{train_symbol}_{label_mode}_h{h}.pkl"
        if not p.exists():
            logging.warning("模型未找到: %s", p)
            continue
        out[h] = load_artifacts(p)
    return out


def _run_one(
    cfg: PredictStrategy5Config,
    *,
    train_symbol: str,
    test_symbol: str,
    label_mode: str,
    horizon_s: int,
    feat: pd.DataFrame,
    feature_cols: list[str],
    art: TrainArtifacts,
) -> CrossSymbolResult:
    X, _, meta = make_dataset_from_features(
        feat,
        horizon_s=horizon_s,
        threshold=cfg.label_threshold,
        mode=label_mode,
        feature_cols=feature_cols,
    )

    proba = art.calibrated_model.predict_proba(X)
    p_down = proba[:, 0].astype(np.float64)
    p_up = proba[:, 2].astype(np.float64)

    pos = positions_from_probs_hysteresis(
        p_up=p_up,
        p_down=p_down,
        p_enter=float(cfg.p_enter),
        p_exit=float(cfg.p_exit),
        diff_enter=float(cfg.diff_enter),
        diff_exit=float(cfg.diff_exit),
        init_pos=0,
    )

    sim = simulate_always_in(
        meta,
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
    total_return = float(net.iloc[-1] - 1.0) if len(net) else 0.0
    max_dd = float(dd.min()) if len(dd) else 0.0
    n_trades = int((sim.turnover > 0).sum())
    total_cost = float(sim.cost.sum())

    return CrossSymbolResult(
        train_symbol=train_symbol,
        test_symbol=test_symbol,
        label_mode=label_mode,
        horizon_s=horizon_s,
        bars=len(sim.equity),
        trades=n_trades,
        return_pct=total_return * 100.0,
        max_dd_pct=max_dd * 100.0,
        cost=total_cost,
    )


def main() -> None:
    cfg = PredictStrategy5Config()

    train_symbol = os.environ.get("PREDICT5_TRAIN_SYMBOL", "BTCUSDT")
    test_symbol = os.environ.get("PREDICT5_TEST_SYMBOL", "ETHUSDC")
    label_mode = os.environ.get("PREDICT5_LABEL_MODE", "executable")

    model_dir = Path(__file__).resolve().parent / "models"
    models = _load_models(model_dir, train_symbol=train_symbol, label_mode=label_mode, horizons_s=list(cfg.horizons_s))
    if not models:
        raise FileNotFoundError(f"未加载到任何模型: model_dir={model_dir}, train_symbol={train_symbol}, mode={label_mode}")

    df_1s, used_days = load_resampled_1s(
        cfg.data_root,
        test_symbol,
        depth_levels=getattr(cfg, "depth_levels", 5),
        start_date=getattr(cfg, "start_date", None),
        end_date=getattr(cfg, "end_date", None),
        max_days=getattr(cfg, "max_days", None),
        cache_1s=getattr(cfg, "cache_1s", True),
        prefer_longest_contiguous=getattr(cfg, "prefer_longest_contiguous", True),
    )
    feat, feature_names = build_features_1s(df_1s)

    if used_days:
        logging.info(
            "Loaded %s: used_days=%s (%s..%s), 1s_bars=%s",
            test_symbol,
            len(used_days),
            used_days[0].name,
            used_days[-1].name,
            f"{len(df_1s):,}",
        )
    else:
        logging.info("Loaded %s: 1s_bars=%s", test_symbol, f"{len(df_1s):,}")

    rows: list[CrossSymbolResult] = []
    for h in sorted(models.keys()):
        rows.append(
            _run_one(
                cfg,
                train_symbol=train_symbol,
                test_symbol=test_symbol,
                label_mode=label_mode,
                horizon_s=h,
                feat=feat,
                feature_cols=feature_names,
                art=models[h],
            )
        )

    df = pd.DataFrame([r.__dict__ for r in rows])
    if df.empty:
        raise ValueError("回测结果为空")

    show = df[["horizon_s", "trades", "return_pct", "max_dd_pct", "cost", "bars"]].copy()
    show["return_pct"] = show["return_pct"].round(3)
    show["max_dd_pct"] = show["max_dd_pct"].round(3)
    show["cost"] = show["cost"].round(2)

    print("\n" + "=" * 72)
    print(f"跨币种回测: Train={train_symbol} -> Test={test_symbol} (mode={label_mode})")
    print("=" * 72)
    print(show.to_string(index=False))


if __name__ == "__main__":
    main()
