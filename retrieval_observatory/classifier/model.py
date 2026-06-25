from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from retrieval_observatory.classifier.data import (
    LabeledQuery,
    check_minimum_samples,
    class_distribution,
    normalize_query_text,
)
from retrieval_observatory.classifier.features import (
    FEATURE_NAMES,
    extract_features,
    features_to_vector,
)
from retrieval_observatory.classifier.labels import CLASS_NAMES, normalize_dataset_name


def _require_sklearn():
    try:
        import sklearn  # noqa: F401
        import joblib  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "Classifier requires scikit-learn and joblib. "
            "Install with: pip install retrieval-observatory[classifier]"
        ) from e


@dataclass
class TrainReport:
    dataset_name: str
    n_samples: int
    class_distribution: Dict[str, int]
    cv_accuracy: float
    cv_macro_f1: float
    cv_brier: float
    calibrated: bool
    warnings: List[str] = field(default_factory=list)
    feature_importances: List[Tuple[str, float]] = field(default_factory=list)
    model_path: str = ""


@dataclass
class QueryDifficultyModel:
    estimator: Any
    metadata: Dict[str, Any]
    feature_importances: Dict[str, float]

    def predict(self, text: str) -> Dict[str, Any]:
        features = extract_features(text)
        X = np.array([features_to_vector(features)], dtype=float)
        proba = self.estimator.predict_proba(X)[0]
        classes = list(self.estimator.classes_)
        proba_dict = {cls: float(p) for cls, p in zip(classes, proba)}
        label = max(proba_dict, key=lambda c: proba_dict[c])

        drivers: List[Dict[str, Any]] = []
        for name in FEATURE_NAMES:
            imp = self.feature_importances.get(name, 0.0)
            val = features.get(name, 0.0)
            drivers.append({"feature": name, "value": val, "importance": imp, "score": val * imp})
        drivers.sort(key=lambda d: d["score"], reverse=True)

        return {
            "label": label,
            "proba": proba_dict,
            "features": features,
            "top_drivers": drivers[:3],
        }


def _build_xy(samples: List[LabeledQuery]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    X = np.array([features_to_vector(extract_features(s.query_text)) for s in samples], dtype=float)
    y = np.array([s.training_class for s in samples])
    groups = np.array([hash(normalize_query_text(s.query_text)) for s in samples])
    return X, y, groups


def _multiclass_brier(y_true: np.ndarray, proba: np.ndarray, classes: List[str]) -> float:
    """Average one-vs-rest Brier score."""
    from sklearn.preprocessing import label_binarize

    y_bin = label_binarize(y_true, classes=classes)
    if y_bin.shape[1] == 1:
        # binary edge case
        y_bin = np.hstack([1 - y_bin, y_bin])
    scores = []
    for i in range(len(classes)):
        scores.append(np.mean((proba[:, i] - y_bin[:, i]) ** 2))
    return float(np.mean(scores))


def cross_validate(samples: List[LabeledQuery], n_splits: int = 5) -> Tuple[float, float, float]:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.model_selection import StratifiedGroupKFold

    X, y, groups = _build_xy(samples)
    n_splits = min(n_splits, len(set(groups)))
    if n_splits < 2:
        return 0.0, 0.0, 0.0

    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=42)

    oof_proba = np.zeros((len(y), len(CLASS_NAMES)))
    y_pred = np.empty(len(y), dtype=object)

    for train_idx, test_idx in sgkf.split(X, y, groups):
        clf = HistGradientBoostingClassifier(
            max_iter=200,
            learning_rate=0.1,
            max_depth=6,
            random_state=42,
        )
        clf.fit(X[train_idx], y[train_idx])
        proba = clf.predict_proba(X[test_idx])
        preds = clf.predict(X[test_idx])
        for i, idx in enumerate(test_idx):
            y_pred[idx] = preds[i]
            for j, cls in enumerate(clf.classes_):
                if cls in CLASS_NAMES:
                    oof_proba[idx, CLASS_NAMES.index(cls)] = proba[i, j]

    acc = accuracy_score(y, y_pred)
    f1 = f1_score(y, y_pred, average="macro", zero_division=0)
    brier = _multiclass_brier(y, oof_proba, list(CLASS_NAMES))
    return float(acc), float(f1), float(brier)


def _compute_permutation_importances(
    X: np.ndarray,
    y: np.ndarray,
    estimator: Any,
) -> List[Tuple[str, float]]:
    from sklearn.inspection import permutation_importance

    n = len(y)
    if n >= 50:
        split = int(n * 0.8)
        X_val, y_val = X[split:], y[split:]
        est = estimator
    else:
        X_val, y_val = X, y
        est = estimator

    result = permutation_importance(
        est, X_val, y_val, n_repeats=10, random_state=42, scoring="f1_macro"
    )
    ranked = sorted(
        zip(FEATURE_NAMES, result.importances_mean),
        key=lambda x: x[1],
        reverse=True,
    )
    return ranked


def train_model(
    samples: List[LabeledQuery],
    dataset_name: str,
    out_path: str,
    min_samples: int = 30,
    min_per_class: int = 5,
) -> TrainReport:
    _require_sklearn()
    import joblib
    import sklearn
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import HistGradientBoostingClassifier

    warnings: List[str] = []
    err = check_minimum_samples(samples, min_samples, min_per_class)
    if err:
        raise ValueError(err)

    dataset_name = normalize_dataset_name(dataset_name)
    acc, f1, brier = cross_validate(samples)
    X, y, _ = _build_xy(samples)

    base = HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.1,
        max_depth=6,
        random_state=42,
    )
    base.fit(X, y)

    dist = class_distribution(samples)
    calibrated = False
    if len(samples) >= 90 and all(dist.get(c, 0) >= 15 for c in CLASS_NAMES):
        final = CalibratedClassifierCV(base, method="isotonic", cv=3)
        final.fit(X, y)
        calibrated = True
    else:
        final = base
        warnings.append(
            "Isotonic calibration skipped (need n>=90 and >=15 per class); using raw probabilities."
        )

    importances = _compute_permutation_importances(X, y, final)
    imp_dict = {name: float(val) for name, val in importances}

    metadata = {
        "dataset_name": dataset_name,
        "feature_names": FEATURE_NAMES,
        "class_names": list(CLASS_NAMES),
        "sklearn_version": sklearn.__version__,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": len(samples),
        "cv_metrics": {"accuracy": acc, "macro_f1": f1, "brier": brier},
        "calibrated": calibrated,
    }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    bundle = {"estimator": final, "metadata": metadata, "feature_importances": imp_dict}
    joblib.dump(bundle, out_path)

    return TrainReport(
        dataset_name=dataset_name,
        n_samples=len(samples),
        class_distribution=dist,
        cv_accuracy=acc,
        cv_macro_f1=f1,
        cv_brier=brier,
        calibrated=calibrated,
        warnings=warnings,
        feature_importances=importances,
        model_path=out_path,
    )


def load_model(path: str) -> QueryDifficultyModel:
    _require_sklearn()
    import joblib

    if not Path(path).exists():
        raise FileNotFoundError(f"Model not found: {path}")
    bundle = joblib.load(path)
    return QueryDifficultyModel(
        estimator=bundle["estimator"],
        metadata=bundle["metadata"],
        feature_importances=bundle.get("feature_importances", {}),
    )


def report_from_samples(samples: List[LabeledQuery], model_path: Optional[str] = None) -> TrainReport:
    """Re-run CV on labeled data; optionally load importances from saved model."""
    warnings: List[str] = []
    if len(samples) < 10:
        warnings.append(f"Only {len(samples)} labeled queries — CV metrics may be unreliable.")

    acc, f1, brier = cross_validate(samples) if len(samples) >= 5 else (0.0, 0.0, 0.0)
    dist = class_distribution(samples)

    importances: List[Tuple[str, float]] = []
    calibrated = False
    dataset_name = ""
    if model_path and Path(model_path).exists():
        model = load_model(model_path)
        dataset_name = model.metadata.get("dataset_name", "")
        calibrated = model.metadata.get("calibrated", False)
        importances = sorted(
            model.feature_importances.items(), key=lambda x: x[1], reverse=True
        )

    return TrainReport(
        dataset_name=dataset_name,
        n_samples=len(samples),
        class_distribution=dist,
        cv_accuracy=acc,
        cv_macro_f1=f1,
        cv_brier=brier,
        calibrated=calibrated,
        warnings=warnings,
        feature_importances=importances,
        model_path=model_path or "",
    )
