"""LightGBM detector -- the reliable workhorse.

This is the tier that ships. It trains in seconds, needs no GPU, produces
calibrated probabilities, and gives exact SHAP attributions for free, which is
what the explainability drawer is built on. The GNN in `gnn.py` is the more
interesting model and it beats this one on the neighbourhood cases, but if the
GNN is unavailable or a training run goes sideways, everything downstream keeps
working on these scores alone.

**Training data.** One row per (incident, candidate account). The same account
appears in several incidents with different features, because its features are
computed as of each complaint time. That is deliberate: the model must score an
account *at a moment*, which is the only way it is ever used.

**Calibration matters more than rank here.** The interdiction cost function
multiplies by `1 - p_mule`, so a miscalibrated score does not just reorder the
plan, it misprices the harm of freezing someone. Probabilities are therefore
isotonically calibrated on a held-out slice rather than used raw.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, roc_auc_score

from app.config import settings
from app.graphstore.features import FEATURE_NAMES, FeatureMatrix

log = logging.getLogger(__name__)


@dataclass
class Detector:
    """A trained model plus the calibration that makes its output a probability."""

    booster: lgb.Booster
    calibrator: IsotonicRegression | None
    feature_names: tuple[str, ...]

    def score(self, matrix: FeatureMatrix) -> np.ndarray:
        if matrix.names != self.feature_names:
            raise ValueError(
                "feature layout changed since training; retrain with `make train`"
            )
        if len(matrix.account_ids) == 0:
            return np.zeros(0, dtype=np.float64)

        raw = self.booster.predict(matrix.values.astype(np.float64))
        raw = np.asarray(raw, dtype=np.float64).ravel()
        if self.calibrator is None:
            return raw
        return np.clip(self.calibrator.predict(raw), 1e-4, 1 - 1e-4)

    def shap(self, matrix: FeatureMatrix) -> np.ndarray:
        """Per-feature contributions. Last column is the base value."""
        contributions = self.booster.predict(
            matrix.values.astype(np.float64), pred_contrib=True
        )
        return np.asarray(contributions, dtype=np.float64)

    def save(self, model_path: Path, meta_path: Path) -> None:
        model_path.parent.mkdir(parents=True, exist_ok=True)
        self.booster.save_model(str(model_path))
        meta: dict[str, object] = {"feature_names": list(self.feature_names)}
        if self.calibrator is not None:
            meta["calibration"] = {
                "x": self.calibrator.X_thresholds_.tolist(),
                "y": self.calibrator.y_thresholds_.tolist(),
            }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, model_path: Path, meta_path: Path) -> "Detector":
        booster = lgb.Booster(model_file=str(model_path))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        calibrator: IsotonicRegression | None = None
        if "calibration" in meta:
            calibrator = IsotonicRegression(out_of_bounds="clip")
            x = np.asarray(meta["calibration"]["x"], dtype=np.float64)
            y = np.asarray(meta["calibration"]["y"], dtype=np.float64)
            calibrator.fit(x, y)

        return cls(
            booster=booster,
            calibrator=calibrator,
            feature_names=tuple(meta["feature_names"]),
        )


def train_detector(
    features: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
) -> tuple[Detector, dict[str, float]]:
    """Fit the detector, holding out whole incidents for calibration.

    Splitting by incident rather than by row is essential. Accounts recur
    across incidents, so a random row split would put the same account on both
    sides and report a validation score that is mostly memorisation.
    """
    unique = np.unique(groups)
    rng = np.random.default_rng(settings.master_seed)
    shuffled = unique.copy()
    rng.shuffle(shuffled)

    cut = max(1, int(len(shuffled) * 0.25))
    calibration_groups = set(shuffled[:cut].tolist())
    is_calibration = np.array([g in calibration_groups for g in groups])

    x_train, y_train = features[~is_calibration], labels[~is_calibration]
    x_valid, y_valid = features[is_calibration], labels[is_calibration]

    params = dict(settings.gbdt_params)
    n_estimators = int(params.pop("n_estimators", 400))
    # Mules are a small minority. Without this the model can score well on
    # accuracy while never separating the class anyone cares about.
    positives = max(int(y_train.sum()), 1)
    params["scale_pos_weight"] = float(len(y_train) - positives) / positives

    booster = lgb.train(
        params,
        lgb.Dataset(x_train, label=y_train, feature_name=list(FEATURE_NAMES)),
        num_boost_round=n_estimators,
        valid_sets=[lgb.Dataset(x_valid, label=y_valid)],
        callbacks=[lgb.early_stopping(40, verbose=False)],
    )

    raw_valid = np.asarray(booster.predict(x_valid), dtype=np.float64).ravel()
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_valid, y_valid)

    detector = Detector(
        booster=booster, calibrator=calibrator, feature_names=FEATURE_NAMES
    )
    metrics = {
        "auc_pr": float(average_precision_score(y_valid, raw_valid)),
        "auc_roc": float(roc_auc_score(y_valid, raw_valid)),
        "n_train_rows": int(len(y_train)),
        "n_valid_rows": int(len(y_valid)),
        "n_train_incidents": int(len(unique) - len(calibration_groups)),
        "positive_rate": float(labels.mean()),
    }
    log.info(
        "gbdt trained on %d rows / %d incidents -- validation AUC-PR %.3f",
        metrics["n_train_rows"],
        metrics["n_train_incidents"],
        metrics["auc_pr"],
    )
    return detector, metrics


def load_detector() -> Detector | None:
    """Load the trained detector, or None if training has not been run."""
    if not (settings.detector_path.exists() and settings.detector_meta_path.exists()):
        return None
    try:
        return Detector.load(settings.detector_path, settings.detector_meta_path)
    except (OSError, ValueError, KeyError) as exc:
        log.warning("could not load detector: %s", exc)
        return None
