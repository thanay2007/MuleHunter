"""Metric definitions, written down once so every surface agrees.

The definitions matter more than the arithmetic. Three of them decide whether
the benchmark means anything:

* **prevented** -- rupees kept inside the banking system that would otherwise
  have left, measured against a do-nothing replay of the same incident. This
  is the headline. It is a counterfactual, so it cannot be inflated by freezing
  accounts that were never going to move.

* **secured** -- rupees sitting under a freeze at the end of the window. A
  weaker claim, reported separately. Money can be secured without any of it
  having been at risk.

* **residual** -- rupees still in the system and unsecured. Not recovered.
  Rolling this into recovery would let the do-nothing policy report a large
  number for having done nothing, which is exactly the trap being avoided.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np


@dataclass
class IncidentOutcome:
    """One policy's result on one incident."""

    incident_id: str
    policy: str
    ring_id: str
    typology: str
    amount_inr: float
    complaint_delay_minutes: int

    prevented_inr: float
    leaked_inr: float
    secured_inr: float
    residual_inr: float
    already_gone_inr: float

    frozen_accounts: int
    innocent_frozen: int
    mules_frozen: int
    first_freeze_minute: int | None
    solve_ms: float

    @property
    def prevention_rate(self) -> float:
        """Share of the money that would have leaked, and did not."""
        would_leak = self.prevented_inr + self.leaked_inr
        return self.prevented_inr / would_leak if would_leak > 0 else 0.0

    @property
    def recovery_rate(self) -> float:
        """Prevented rupees as a share of the amount stolen."""
        return self.prevented_inr / self.amount_inr if self.amount_inr > 0 else 0.0

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["prevention_rate"] = round(self.prevention_rate, 4)
        data["recovery_rate"] = round(self.recovery_rate, 4)
        return data


@dataclass
class PolicySummary:
    """Aggregate performance of one policy across the benchmark."""

    policy: str
    n_incidents: int

    recovery_rate_mean: float
    recovery_rate_median: float
    prevention_rate_mean: float

    prevented_inr_total: float
    leaked_inr_total: float
    stolen_inr_total: float

    innocent_frozen_total: int
    innocent_frozen_mean: float
    innocent_frozen_rate: float
    frozen_accounts_mean: float
    precision: float

    time_to_first_freeze_median: float
    solve_ms_p50: float
    solve_ms_p95: float

    recovery_rate_p10: float = 0.0
    recovery_rate_p90: float = 0.0
    histogram: list[int] = field(default_factory=list)


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else 0.0


def summarise(policy: str, outcomes: list[IncidentOutcome]) -> PolicySummary:
    """Roll a policy's per-incident outcomes into the published summary."""
    if not outcomes:
        return PolicySummary(
            policy=policy,
            n_incidents=0,
            recovery_rate_mean=0.0,
            recovery_rate_median=0.0,
            prevention_rate_mean=0.0,
            prevented_inr_total=0.0,
            leaked_inr_total=0.0,
            stolen_inr_total=0.0,
            innocent_frozen_total=0,
            innocent_frozen_mean=0.0,
            innocent_frozen_rate=0.0,
            frozen_accounts_mean=0.0,
            precision=0.0,
            time_to_first_freeze_median=0.0,
            solve_ms_p50=0.0,
            solve_ms_p95=0.0,
        )

    recovery = [o.recovery_rate for o in outcomes]
    prevention = [o.prevention_rate for o in outcomes]
    solve = [o.solve_ms for o in outcomes]
    first = [
        float(o.first_freeze_minute - o.complaint_delay_minutes)
        for o in outcomes
        if o.first_freeze_minute is not None
    ]

    frozen = sum(o.frozen_accounts for o in outcomes)
    innocent = sum(o.innocent_frozen for o in outcomes)

    # Recovery-rate distribution in ten buckets, for the histogram.
    histogram = [0] * 10
    for rate in recovery:
        histogram[min(9, max(0, int(rate * 10)))] += 1

    return PolicySummary(
        policy=policy,
        n_incidents=len(outcomes),
        recovery_rate_mean=round(float(np.mean(recovery)), 4),
        recovery_rate_median=round(float(np.median(recovery)), 4),
        prevention_rate_mean=round(float(np.mean(prevention)), 4),
        prevented_inr_total=round(sum(o.prevented_inr for o in outcomes), 2),
        leaked_inr_total=round(sum(o.leaked_inr for o in outcomes), 2),
        stolen_inr_total=round(sum(o.amount_inr for o in outcomes), 2),
        innocent_frozen_total=innocent,
        innocent_frozen_mean=round(innocent / len(outcomes), 3),
        # Of every account frozen, what share belonged to someone innocent.
        innocent_frozen_rate=round(innocent / frozen, 4) if frozen else 0.0,
        frozen_accounts_mean=round(frozen / len(outcomes), 2),
        precision=round(
            sum(o.mules_frozen for o in outcomes) / frozen, 4
        ) if frozen else 0.0,
        time_to_first_freeze_median=round(float(np.median(first)), 2) if first else 0.0,
        solve_ms_p50=round(percentile(solve, 50), 2),
        solve_ms_p95=round(percentile(solve, 95), 2),
        recovery_rate_p10=round(percentile(recovery, 10), 4),
        recovery_rate_p90=round(percentile(recovery, 90), 4),
        histogram=histogram,
    )


def format_summary_table(summaries: list[PolicySummary]) -> str:
    header = (
        f"{'policy':<24}{'recovery':>10}{'median':>9}{'prevented ₹':>15}"
        f"{'leaked ₹':>15}{'innocent':>10}{'frozen':>8}{'p95 ms':>9}"
    )
    lines = [header, "-" * len(header)]
    for summary in summaries:
        lines.append(
            f"{summary.policy:<24}"
            f"{summary.recovery_rate_mean:>9.1%} "
            f"{summary.recovery_rate_median:>8.1%}"
            f"{summary.prevented_inr_total:>15,.0f}"
            f"{summary.leaked_inr_total:>15,.0f}"
            f"{summary.innocent_frozen_total:>10d}"
            f"{summary.frozen_accounts_mean:>8.1f}"
            f"{summary.solve_ms_p95:>9.0f}"
        )
    return "\n".join(lines)
