"""Putting four systems on the same operating point.

Most of the apparent gap between detection systems is not a gap in the systems.
It is a gap in where their thresholds happen to sit. Comparing a model tuned for
recall against one tuned for precision measures the tuning, and a judge who has
seen that trick once will assume it is being played again unless the
counter-argument is on screen before they ask.

Three modes, fitted on `val` only and applied identically to all four:

  equal_alert_budget   every system may flag exactly N accounts per case.
                       The default, and the operationally honest one: an
                       investigation desk has a fixed daily capacity, so this is
                       the comparison that matches how the alerts get worked.
                       It is also the only mode in which "flag everything" is
                       not a winning strategy.

  equal_fpr            per-system thresholds chosen so all four hit the same
                       false-positive rate on `val`. Answers the different
                       question -- at equal collateral damage, who finds more.

  native               each repository's own published threshold. The operating
                       points differ, so the counts are not comparable; it is
                       here because refusing to show it would look like hiding
                       something, and because it is what each system would
                       actually do out of the box.

A system that only emits hard labels cannot participate in the first two. It is
excluded rather than given a fabricated score, marked `binary`, and badged in
the Arena as native-threshold-only. Pretending a binary model has a tunable
threshold is the single easiest way to produce a bogus comparison.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("bench.calibrate")

DEFAULT_BUDGET = 12
DEFAULT_TARGET_FPR = 0.12


@dataclass(frozen=True)
class OperatingPoint:
    mode: str
    budget: int
    threshold: float
    calibration_note: str
    val_fpr: float = 0.0
    val_tpr: float = 0.0
    applicable: bool = True

    def to_json(self) -> dict:
        return {
            "mode": self.mode,
            "budget": self.budget,
            "threshold": round(float(self.threshold), 6),
            "calibration_note": self.calibration_note,
            "val_fpr": round(float(self.val_fpr), 4),
            "val_tpr": round(float(self.val_tpr), 4),
            "applicable": self.applicable,
        }


def _rates(
    scores: dict[str, float], truth: dict[str, str], threshold: float
) -> tuple[float, float]:
    """(FPR, TPR) at a threshold, over whatever accounts were scored."""
    tp = fp = pos = neg = 0
    for account, score in scores.items():
        is_mule = truth.get(account) == "mule"
        if is_mule:
            pos += 1
            if score >= threshold:
                tp += 1
        else:
            neg += 1
            if score >= threshold:
                fp += 1
    return (fp / neg if neg else 0.0, tp / pos if pos else 0.0)


def fit(
    val_scores: list[dict[str, float]],
    val_truth: list[dict[str, str]],
    *,
    score_kind: str,
    native_threshold: float | None,
    native_flags: list[dict[str, bool]] | None,
    budget: int = DEFAULT_BUDGET,
    target_fpr: float = DEFAULT_TARGET_FPR,
) -> dict[str, OperatingPoint]:
    """Fit all three operating points for one system, on the validation split.

    `val_scores` is one dict per validation case. Pooling the cases before
    choosing a threshold is deliberate: a threshold fitted per case would be
    fitted to the answer, and the whole point of a held-out split is that the
    threshold was chosen without seeing the case it is applied to.
    """
    binary = score_kind == "binary"

    pooled_scores: dict[str, float] = {}
    pooled_truth: dict[str, str] = {}
    for n, (scores, truth) in enumerate(zip(val_scores, val_truth)):
        for account, score in scores.items():
            key = f"{n}:{account}"
            pooled_scores[key] = score
            pooled_truth[key] = truth.get(account, "innocent")

    # --- equal alert budget -------------------------------------------------
    # The cut is a rank, not a score, so the only threshold it needs is a floor
    # that stops a system flagging accounts it scored at zero just to fill its
    # quota. A system with nothing to say should be allowed to say nothing.
    budget_point = OperatingPoint(
        mode="equal_alert_budget",
        budget=budget,
        threshold=1e-9,
        calibration_note=(
            f"Every system may flag at most {budget} accounts per case, ranked by "
            "its own score. An investigation desk has a fixed daily capacity, so "
            "this is the comparison that matches how the alerts would be worked."
        ),
        applicable=not binary,
    )

    # --- equal false-positive rate ------------------------------------------
    innocent = sorted(
        (s for k, s in pooled_scores.items() if pooled_truth[k] != "mule"), reverse=True
    )
    if innocent and not binary:
        allowed = max(0, int(round(target_fpr * len(innocent))))
        fpr_threshold = innocent[allowed - 1] if allowed >= 1 else innocent[0] + 1e-9
    else:
        fpr_threshold = 1.0
    fpr, tpr = _rates(pooled_scores, pooled_truth, fpr_threshold)
    fpr_point = OperatingPoint(
        mode="equal_fpr",
        budget=10**6,
        threshold=fpr_threshold,
        calibration_note=(
            f"Threshold chosen on the validation split so every system flags "
            f"{target_fpr:.0%} of the innocent accounts it sees. Equal collateral "
            "damage; the question is who finds more inside that budget."
        ),
        val_fpr=fpr,
        val_tpr=tpr,
        applicable=not binary,
    )

    # --- native --------------------------------------------------------------
    if native_flags:
        flagged = [
            pooled_scores[f"{n}:{account}"]
            for n, table in enumerate(native_flags)
            for account, on in table.items()
            if on and f"{n}:{account}" in pooled_scores
        ]
        native = min(flagged) if flagged else 1.0
        note = (
            "The system's own hard label, at the threshold its authors published. "
            "Not comparable to the other modes; shown because it is what this "
            "system does out of the box."
        )
    elif native_threshold is not None:
        native = float(native_threshold)
        note = (
            "The threshold published in the system's own repository. Operating "
            "points differ between systems in this mode, so the counts are not "
            "directly comparable."
        )
    else:
        native = 0.5
        note = (
            "No published threshold found in the system's repository; 0.5 assumed "
            "and recorded as an assumption rather than a finding."
        )
    n_fpr, n_tpr = _rates(pooled_scores, pooled_truth, native)
    native_point = OperatingPoint(
        mode="native",
        budget=10**6,
        threshold=native,
        calibration_note=note,
        val_fpr=n_fpr,
        val_tpr=n_tpr,
        applicable=True,
    )

    if binary:
        log.info(
            "binary-only system: excluded from equal_alert_budget and equal_fpr sweeps"
        )

    return {
        "equal_alert_budget": budget_point,
        "equal_fpr": fpr_point,
        "native": native_point,
    }


def apply(
    scores: dict[str, float], point: OperatingPoint
) -> dict[str, bool]:
    """Turn scores into flags under one operating point. No system-specific paths."""
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    out: dict[str, bool] = {}
    for rank, (account, score) in enumerate(ranked, start=1):
        out[account] = rank <= point.budget and score >= point.threshold
    return out
