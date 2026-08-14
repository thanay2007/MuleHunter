"""Why this account, and what freezing it was worth.

Three things a judge can ask about any node on the canvas, answered from data
rather than from a template:

1. **How does it differ from an ordinary account?** Its features against the
   population median, as signed deviations.
2. **What drove the score?** Exact SHAP attributions from the LightGBM model,
   rendered into plain language -- "dormant for 214 days before activation",
   not `dormancy_days = 214.0`.
3. **What did freezing it actually save, and what would waiting have cost?**
   The marginal recovery, recomputed by re-running the cached rollouts with
   that single freeze delayed.

The third is the one that matters. "Freezing this account at T+6 saved
₹4,12,000; at T+20 it would have saved ₹90,000" is a sentence about *this
account in this incident*, and no amount of model architecture substitutes
for it in a judging conversation.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np

from app.config import settings
from app.detect.gbdt import Detector
from app.graphstore.features import FEATURE_LABELS, FeatureMatrix
from app.interdict.propagate import RolloutSet

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Attribution:
    """One feature's contribution to an account's score."""

    feature: str
    label: str
    value: float
    shap: float
    population_median: float
    direction: str  # "raises" | "lowers"

    @property
    def magnitude(self) -> float:
        return abs(self.shap)


@dataclass(frozen=True)
class MarginalRecovery:
    """What this freeze was worth, and what delay would have cost."""

    issued_at_minute: int
    saved_inr: float
    alternatives: tuple[tuple[int, float], ...]  # (minute, saved) pairs


def attributions(
    detector: Detector | None,
    matrix: FeatureMatrix,
    account_id: str,
    top_n: int = 5,
) -> list[Attribution]:
    """Top SHAP attributions for one account, with plain-language labels."""
    if account_id not in matrix.index:
        return []

    row_index = matrix.index[account_id]
    values = matrix.values[row_index]
    medians = np.median(matrix.values, axis=0)

    if detector is None:
        # No model: rank by how far each feature sits from the population, so
        # the drawer still explains something rather than going blank.
        spread = np.std(matrix.values, axis=0)
        contributions = (values - medians) / np.maximum(spread, 1e-6)
    else:
        single = FeatureMatrix(
            account_ids=(account_id,),
            values=values.reshape(1, -1),
            names=matrix.names,
        )
        contributions = detector.shap(single)[0][:-1]  # drop the base value

    order = np.argsort(-np.abs(contributions))[:top_n]
    return [
        Attribution(
            feature=matrix.names[i],
            label=FEATURE_LABELS.get(matrix.names[i], matrix.names[i]),
            value=float(values[i]),
            shap=float(contributions[i]),
            population_median=float(medians[i]),
            direction="raises" if contributions[i] >= 0 else "lowers",
        )
        for i in order
    ]


def reason_codes(detector, matrix: FeatureMatrix, account_id: str, top_n: int = 3) -> list[str]:
    """The strongest reasons this account was flagged, in plain language.

    Lives here rather than in a route because three surfaces need exactly the
    same sentences: the console's freeze queue, the issued freeze order, and
    the audit trail. "Why was my customer's account frozen" is the first
    question a real bank asks, and answering it differently in the document
    than on the screen would be worse than not answering it at all.
    """
    found = attributions(detector, matrix, account_id, top_n=top_n)
    return [phrase(a) for a in found if a.direction == "raises"][:top_n]


def phrase(attribution: Attribution) -> str:
    """Turn one attribution into a sentence a non-specialist can read."""
    name = attribution.feature
    value = attribution.value

    if name == "dormancy_days":
        return f"dormant for {value:,.0f} days before it woke up"
    if name == "device_cluster_size" and value > 1:
        return f"shares a device with {value - 1:,.0f} other accounts"
    if name == "device_peers_in_incident" and value > 0:
        return f"{value:,.0f} accounts on the same device are in this incident"
    if name == "ip_cluster_size" and value > 1:
        return f"shares an IP range with {value - 1:,.0f} other accounts"
    if name == "median_residence_minutes":
        if value < 60:
            return f"forwards money {value:,.0f} minutes after receiving it"
        return f"holds money for {value / 60:,.1f} hours before forwarding"
    if name == "structuring_band_share" and value > 0:
        return f"{value:.0%} of its transfers sit just under ₹50,000"
    if name == "same_window_openings" and value > 0:
        return f"{value:,.0f} of its counterparties opened accounts the same fortnight"
    if name == "recipient_jaccard_max" and value > 0:
        return f"{value:.0%} of its payee list is shared with another account"
    if name == "hops_to_exit":
        if value >= 90:
            return "no path to a cash-out point"
        return f"{value:,.0f} hops from a cash-out point"
    if name == "hops_from_victim":
        return f"{value:,.0f} hops from the victim"
    if name == "turnover_ratio":
        return f"forwarded {value:.0%} of everything it received"
    if name == "account_age_days":
        return f"account is {value / 365:,.1f} years old"
    if name == "max_fanout_10min":
        return f"paid {value:,.0f} recipients within ten minutes"
    if name in ("exchange_flag", "crossborder_flag", "exit_adjacent") and value > 0:
        return {
            "exchange_flag": "pays into a crypto exchange deposit account",
            "crossborder_flag": "sends money cross-border",
            "exit_adjacent": "is one hop from a cash-out point",
        }[name]
    if name == "log_max_credit":
        return f"largest single credit was ₹{math.expm1(value):,.0f}"
    if name == "log_total_out":
        return f"sent ₹{math.expm1(value):,.0f} in total"
    if name == "activity_span_hours":
        if value < 24:
            return f"all of its activity falls inside {value:,.0f} hours"
        return f"active across {value / 24:,.0f} days"
    if name == "in_degree":
        return f"receives from {value:,.0f} accounts"
    if name == "out_degree":
        return f"sends to {value:,.0f} accounts"
    if name == "fanout_ratio":
        return f"{value:,.1f} recipients for every sender"
    if name == "night_activity_share" and value > 0:
        return f"{value:.0%} of its activity is between 23:00 and 05:00"
    if name == "amount_cv":
        if value < 0.35:
            return f"its outgoing amounts are unusually uniform (spread {value:.2f})"
        return f"spread of its outgoing amounts is {value:.2f}"
    if name == "round_amount_share" and value > 0:
        return f"{value:.0%} of its transfers are round numbers"
    if name == "reciprocity":
        if value < 0.05:
            return "never pays anyone who pays it — money only flows one way"
        return f"{value:.0%} of its counterparties are two-way"
    if name == "outflow_within_10min_share" and value > 0:
        return f"{value:.0%} of its transfers go out within ten minutes"
    if name.startswith("in_out_ratio_"):
        window = name.rsplit("_", 1)[1]
        return f"sent {value:,.1f}x what it received in the last {window}"
    if name == "atm_value_share" and value > 0:
        return f"{value:.0%} of what it sends is withdrawn as cash"
    if name == "burstiness":
        return f"activity is clustered rather than steady (index {value:,.1f})"
    if name == "txn_count":
        return f"{value:,.0f} transfers in the window"
    if name == "pagerank":
        return f"centrality {value:.4f} in the incident graph"
    if name == "betweenness":
        if value > 0.01:
            return f"a bottleneck — {value:.1%} of paths run through it"
        return "not on the critical path of the money"
    if name == "kyc_video_flag" and value > 0:
        return "opened by video KYC"
    if name == "kyc_small_flag" and value > 0:
        return "a small account with limited KYC"

    return f"{attribution.label} — {value:,.2f}"


def marginal_recovery(
    rollouts: RolloutSet,
    account_id: str,
    issued_at_minute: int,
    other_freezes: dict[str, int] | None = None,
    probe_minutes: tuple[int, ...] = (),
) -> MarginalRecovery:
    """What this one freeze saved, and what it would have saved issued later.

    Computed by replaying the cached rollouts with every *other* freeze in the
    plan held fixed and this one moved in time. Holding the rest fixed is the
    point: it measures this account's contribution to the plan that was
    actually issued, not its value in isolation, and those differ whenever two
    freezes cover the same money.
    """
    blocking = rollouts.blocking_index()
    mine = blocking.get(account_id, {})
    others = dict(other_freezes or {})
    others.pop(account_id, None)

    escapes = np.array(
        [1.0 if p.exited else 0.0 for p in rollouts.particles], dtype=np.float64
    )
    weights = escapes + settings.parked_money_weight
    n = max(rollouts.n_rollouts, 1)
    effectiveness = settings.action_effectiveness["full_freeze"]

    # Probability each parcel escapes the rest of the plan.
    survival = np.ones(len(rollouts.particles), dtype=np.float64)
    for account, at_minute in others.items():
        for particle, departs in blocking.get(account, {}).items():
            if departs >= at_minute:
                survival[particle] *= 1.0 - effectiveness

    def saved_if_issued_at(at_minute: int) -> float:
        total = 0.0
        for particle, departs in mine.items():
            if departs >= at_minute:
                total += (
                    rollouts.values[particle]
                    * weights[particle]
                    * survival[particle]
                    * effectiveness
                )
        return round(total / n, 2)

    probes = probe_minutes or _default_probes(issued_at_minute)
    return MarginalRecovery(
        issued_at_minute=issued_at_minute,
        saved_inr=saved_if_issued_at(issued_at_minute),
        alternatives=tuple(
            (minute, saved_if_issued_at(minute)) for minute in probes
        ),
    )


def _default_probes(issued_at_minute: int) -> tuple[int, ...]:
    """A few later issue times, to show how fast the opportunity decays."""
    return tuple(
        issued_at_minute + offset for offset in (15, 30, 60)
    )
