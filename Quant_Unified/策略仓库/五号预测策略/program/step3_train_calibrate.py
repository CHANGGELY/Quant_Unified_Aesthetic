from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


@dataclass(frozen=True)
class TrainArtifacts:
    model_name: str
    base_model: Any
    calibrated_model: Any
    feature_names: list[str]


class OneVsRestProbCalibrator:
    """
    多分类概率校准（one-vs-rest）：
    - method="sigmoid": Platt scaling（对 logit(p) 做逻辑回归）
    - method="isotonic": isotonic regression
    """

    def __init__(self, base_model: Any, method: str = "sigmoid", eps: float = 1e-6):
        self.base_model = base_model
        self.method = method
        self.eps = eps
        self.classes_: np.ndarray | None = None
        self._calibrators: list[Any | None] = []

    def fit(self, X: pd.DataFrame, y: pd.Series):
        if self.method not in {"sigmoid", "isotonic"}:
            raise ValueError("method must be 'sigmoid' or 'isotonic'")

        y_arr = y.to_numpy()
        self.classes_ = np.unique(y_arr)

        raw = np.asarray(self.base_model.predict_proba(X), dtype=float)
        n_classes = raw.shape[1]

        self._calibrators = []
        for k in range(n_classes):
            yk = (y_arr == k).astype(int)
            pk = raw[:, k]

            # 若该类在校准集样本过少，则跳过校准（保持原概率）
            if yk.min() == yk.max():
                self._calibrators.append(None)
                continue

            if self.method == "isotonic":
                iso = IsotonicRegression(out_of_bounds="clip")
                iso.fit(pk, yk)
                self._calibrators.append(iso)
            else:
                pk_clip = np.clip(pk, self.eps, 1.0 - self.eps)
                score = np.log(pk_clip / (1.0 - pk_clip)).reshape(-1, 1)
                lr = LogisticRegression(max_iter=1000, random_state=42)
                lr.fit(score, yk)
                self._calibrators.append(lr)

        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        raw = np.asarray(self.base_model.predict_proba(X), dtype=float)
        out = raw.copy()

        for k, cal in enumerate(self._calibrators):
            if cal is None:
                continue
            pk = raw[:, k]
            if isinstance(cal, IsotonicRegression):
                out[:, k] = cal.transform(pk)
            else:
                pk_clip = np.clip(pk, self.eps, 1.0 - self.eps)
                score = np.log(pk_clip / (1.0 - pk_clip)).reshape(-1, 1)
                out[:, k] = cal.predict_proba(score)[:, 1]

        s = out.sum(axis=1, keepdims=True)
        ok = s[:, 0] > 0
        out[ok] = out[ok] / s[ok]
        out[~ok] = raw[~ok]
        return out
def build_base_estimator(random_state: int = 42):
    """
    强制使用 LightGBM（SOTA 方案）；若缺少依赖请先安装。
    """
    try:
        import lightgbm as lgb  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "未安装/无法导入 lightgbm。\n"
            "如果是 macOS，请确保已安装 libomp (OpenMP):\n"
            "  brew install libomp\n"
            "如果是 python 依赖缺失:\n"
            "  python3 -m pip install lightgbm"
        ) from e

    model = lgb.LGBMClassifier(
        objective="multiclass",
        num_class=3,
        n_estimators=300,
        learning_rate=0.05,
        num_leaves=63,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=random_state,
        n_jobs=-1,
        class_weight="balanced",
        force_row_wise=True,
        verbosity=-1,
    )
    return "lightgbm", model


def time_split(X: pd.DataFrame, y: pd.Series, train_frac: float, calib_frac: float):
    if not (0.0 < train_frac < 1.0):
        raise ValueError("train_frac must be in (0,1)")
    if not (0.0 < calib_frac < 1.0):
        raise ValueError("calib_frac must be in (0,1)")
    if train_frac + calib_frac >= 1.0:
        raise ValueError("train_frac + calib_frac must be < 1")

    n = len(X)
    n_train = int(n * train_frac)
    n_cal = int(n * calib_frac)
    n_cal_end = n_train + n_cal

    X_train = X.iloc[:n_train]
    y_train = y.iloc[:n_train]
    X_cal = X.iloc[n_train:n_cal_end]
    y_cal = y.iloc[n_train:n_cal_end]
    X_test = X.iloc[n_cal_end:]
    y_test = y.iloc[n_cal_end:]
    return X_train, y_train, X_cal, y_cal, X_test, y_test


def train_and_calibrate(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_cal: pd.DataFrame,
    y_cal: pd.Series,
    calib_method: str = "sigmoid",
    random_state: int = 42,
) -> TrainArtifacts:
    model_name, base = build_base_estimator(random_state=random_state)
    base.fit(X_train, y_train)

    if calib_method not in {"sigmoid", "isotonic"}:
        raise ValueError("calib_method must be 'sigmoid' or 'isotonic'")

    calibrated = OneVsRestProbCalibrator(base, method=calib_method).fit(X_cal, y_cal)

    return TrainArtifacts(
        model_name=model_name,
        base_model=base,
        calibrated_model=calibrated,
        feature_names=list(X_train.columns),
    )


def save_artifacts(art: TrainArtifacts, path: Path | str) -> None:
    import joblib
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(art, path)


def load_artifacts(path: Path | str) -> TrainArtifacts:
    import joblib
    return joblib.load(path)



def top_feature_importance(art: TrainArtifacts, top_n: int = 20) -> list[tuple[str, float]]:
    base = art.base_model
    if hasattr(base, "feature_importances_"):
        imp = np.asarray(getattr(base, "feature_importances_"), dtype=float)
        pairs = list(zip(art.feature_names, imp))
        pairs.sort(key=lambda x: x[1], reverse=True)
        return pairs[:top_n]
    return []
