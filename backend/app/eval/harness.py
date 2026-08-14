"""The 200-incident benchmark.

    python -m app.eval.harness

Runs all four policies over incidents drawn exclusively from held-out rings and
writes `data/benchmark.json`, which the Evaluation route renders directly. No
number in the UI is typed by hand; if this file is not regenerated, the tab
says so rather than showing something stale.

What is measured, and why each one is here:

* **recovery rate** -- prevented rupees over stolen rupees. Mean, median and
  distribution, because the mean alone hides that some incidents are hopeless.
* **innocent accounts frozen** -- the cost side of the ledger. Reported per
  policy at the same freeze budget, so it cannot be traded away quietly.
* **time to first freeze** -- minutes after the complaint.
* **recovery vs complaint delay** -- the same episodes replayed at ten
  different delays. This is the most persuasive chart in the project: it puts
  a rupee value on the golden hour.
* **innocence budget sweep** -- what tightening `B` costs in recovery.
* **solver latency** -- p50 and p95, because "does it run fast enough" is a
  fair question and should have a measured answer.
* **greedy optimality gap** -- against CP-SAT on incidents small enough to
  solve exactly.
* **adaptive adversary** -- every headline rerun against an operator who
  reroutes blocked money. Reported next to the passive figure rather than
  instead of it.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict

import numpy as np

from app.config import settings
from app.detect.gbdt import load_detector
from app.graphstore.build import load_dataset
from app.graphstore.incidents import Incident, benchmark_incidents
from app.graphstore.trace import transaction_index
from app.interdict.exact_cpsat import solve_exact
from app.interdict.greedy import FreezePlan
from app.interdict.policies import (
    POLICIES,
    POLICY_LABELS,
    IncidentContext,
    build_context,
    plan_for,
)
from app.interdict.replay import replay
from app.eval.metrics import IncidentOutcome, format_summary_table, summarise

log = logging.getLogger(__name__)


def evaluate_incident(
    context: IncidentContext,
    policy: str,
    mule_ids: frozenset[str],
    index,
    baseline_leak: float,
    budget_k: int | None = None,
    innocence_budget: float | None = None,
    reroute_prob: float | None = None,
) -> IncidentOutcome:
    """Plan under one policy and score it against the real timeline."""
    started = time.perf_counter()
    plan = plan_for(policy, context, budget_k, innocence_budget)
    solve_ms = (time.perf_counter() - started) * 1000

    result = replay(
        context.state,
        plan,
        settings.incident_horizon_hours * 60,
        mule_ids,
        index,
        reroute_prob=reroute_prob,
    )
    incident = context.incident

    return IncidentOutcome(
        incident_id=incident.incident_id,
        policy=policy,
        ring_id=incident.ring_id,
        typology=incident.typology,
        amount_inr=incident.amount_inr,
        complaint_delay_minutes=incident.complaint_delay_minutes,
        prevented_inr=round(max(0.0, baseline_leak - result.leaked_inr), 2),
        leaked_inr=result.leaked_inr,
        secured_inr=result.recovered_inr,
        residual_inr=result.residual_inr,
        already_gone_inr=result.already_gone_inr,
        frozen_accounts=len(plan.steps),
        innocent_frozen=result.innocent_frozen,
        mules_frozen=result.mules_frozen,
        first_freeze_minute=result.first_freeze_minute,
        solve_ms=round(solve_ms, 2),
    )


def run(
    incidents: list[Incident] | None = None,
    with_exact: bool = True,
    with_curves: bool = True,
) -> dict[str, object]:
    started = time.perf_counter()
    dataset = load_dataset()
    index = transaction_index()
    detector = load_detector()
    mules = dataset.mule_ids
    horizon = settings.incident_horizon_hours * 60

    pool = list(incidents) if incidents is not None else list(benchmark_incidents())
    log.info("benchmarking %d incidents across %d policies", len(pool), len(POLICIES))

    outcomes: dict[str, list[IncidentOutcome]] = {p: [] for p in POLICIES}
    adaptive: dict[str, list[IncidentOutcome]] = {p: [] for p in POLICIES}
    delay_rows: list[dict[str, object]] = []
    innocence_rows: list[dict[str, object]] = []
    exact_rows: list[dict[str, object]] = []

    for position, incident in enumerate(pool):
        context = build_context(incident, dataset, index, detector)
        # Every policy is scored against the same do-nothing replay of the same
        # incident, so "prevented" is a true counterfactual.
        nothing = replay(
            context.state, FreezePlan(), horizon, mules, index, reroute_prob=0.0
        )

        for policy in POLICIES:
            outcomes[policy].append(
                evaluate_incident(
                    context, policy, mules, index, nothing.leaked_inr, reroute_prob=0.0
                )
            )
            adaptive[policy].append(
                evaluate_incident(
                    context,
                    policy,
                    mules,
                    index,
                    nothing.leaked_inr,
                    reroute_prob=settings.adversary_reroute_prob,
                )
            )

        if with_exact and len(exact_rows) < settings.benchmark_exact_incidents:
            exact_rows.extend(_exact_gap(context))

        if with_curves and position < settings.benchmark_curve_incidents:
            delay_rows.extend(
                _delay_curve(incident, dataset, index, detector, mules, horizon)
            )
            innocence_rows.extend(_innocence_curve(context, mules, index, nothing))

        if position % 20 == 0:
            log.info("  %d/%d incidents", position + 1, len(pool))

    summaries = [summarise(policy, outcomes[policy]) for policy in POLICIES]
    adaptive_summaries = [summarise(policy, adaptive[policy]) for policy in POLICIES]

    report: dict[str, object] = {
        "generated_seconds": round(time.perf_counter() - started, 1),
        "n_incidents": len(pool),
        "holdout_rings": list(settings.holdout_ring_ids),
        "budget_k": settings.default_budget_k,
        "innocence_budget": settings.default_innocence_budget,
        "policy_labels": POLICY_LABELS,
        "policies": [asdict(s) for s in summaries],
        "policies_adaptive_adversary": [asdict(s) for s in adaptive_summaries],
        "adversary_reroute_prob": settings.adversary_reroute_prob,
        "recovery_vs_delay": _aggregate_delay(delay_rows),
        "innocence_sweep": _aggregate_innocence(innocence_rows),
        "optimality_gap": _aggregate_exact(exact_rows),
        "incidents": [o.to_dict() for o in outcomes["chakravyuh_greedy"]],
    }

    settings.benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    settings.benchmark_path.write_text(
        json.dumps(report, indent=2, default=float), encoding="utf-8"
    )
    log.info("wrote %s", settings.benchmark_path)
    return report


# ---------------------------------------------------------------------------
# curves
# ---------------------------------------------------------------------------


def _delay_curve(
    incident: Incident,
    dataset,
    index,
    detector,
    mules: frozenset[str],
    horizon: int,
) -> list[dict[str, object]]:
    """Replay one episode at every complaint delay on the grid.

    The same money, the same ring, the same budget -- only the delay changes.
    That isolation is what makes the resulting curve an argument rather than a
    correlation.
    """
    rows: list[dict[str, object]] = []
    for delay in settings.benchmark_delay_grid:
        variant = incident.with_delay(delay)
        context = build_context(variant, dataset, index, detector)
        nothing = replay(
            context.state, FreezePlan(), horizon, mules, index, reroute_prob=0.0
        )
        for policy in ("named_account_only", "chakravyuh_greedy"):
            outcome = evaluate_incident(
                context, policy, mules, index, nothing.leaked_inr, reroute_prob=0.0
            )
            rows.append(
                {
                    "delay": delay,
                    "policy": policy,
                    "recovery_rate": outcome.recovery_rate,
                    "prevented_inr": outcome.prevented_inr,
                }
            )
    return rows


def _innocence_curve(
    context: IncidentContext, mules: frozenset[str], index, nothing
) -> list[dict[str, object]]:
    """How recovery responds as the innocence budget tightens."""
    rows: list[dict[str, object]] = []
    for budget in settings.benchmark_innocence_grid:
        outcome = evaluate_incident(
            context,
            "chakravyuh_greedy",
            mules,
            index,
            nothing.leaked_inr,
            innocence_budget=budget,
            reroute_prob=0.0,
        )
        rows.append(
            {
                "innocence_budget": budget,
                "recovery_rate": outcome.recovery_rate,
                "innocent_frozen": outcome.innocent_frozen,
                "frozen_accounts": outcome.frozen_accounts,
            }
        )
    return rows


def _exact_gap(context: IncidentContext) -> list[dict[str, object]]:
    """Greedy versus CP-SAT on one incident, if it is small enough."""
    plan = plan_for("chakravyuh_greedy", context)
    result = solve_exact(
        context.rollouts, context.p_mule, context.activity_weight, plan
    )
    if not result.solved:
        return []
    return [
        {
            "incident_id": context.incident.incident_id,
            "accounts": result.n_accounts,
            "greedy_inr": result.greedy_value_inr,
            "optimal_inr": result.optimal_value_inr,
            "gap": round(result.gap, 4),
            "cpsat_ms": round(result.solve_ms, 1),
            "status": result.status,
        }
    ]


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def _aggregate_delay(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for delay in settings.benchmark_delay_grid:
        entry: dict[str, object] = {"delay_minutes": delay}
        for policy in ("named_account_only", "chakravyuh_greedy"):
            matching = [
                float(r["recovery_rate"])
                for r in rows
                if r["delay"] == delay and r["policy"] == policy
            ]
            entry[policy] = round(float(np.mean(matching)), 4) if matching else 0.0
        out.append(entry)
    return out


def _aggregate_innocence(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for budget in settings.benchmark_innocence_grid:
        matching = [r for r in rows if r["innocence_budget"] == budget]
        if not matching:
            continue
        out.append(
            {
                "innocence_budget": budget,
                "recovery_rate": round(
                    float(np.mean([float(r["recovery_rate"]) for r in matching])), 4
                ),
                "innocent_frozen_mean": round(
                    float(np.mean([float(r["innocent_frozen"]) for r in matching])), 3
                ),
                "frozen_accounts_mean": round(
                    float(np.mean([float(r["frozen_accounts"]) for r in matching])), 2
                ),
            }
        )
    return out


def _aggregate_exact(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        return {"n_incidents": 0, "note": "no incidents small enough to solve exactly"}
    gaps = [float(r["gap"]) for r in rows]
    return {
        "n_incidents": len(rows),
        "mean_gap": round(float(np.mean(gaps)), 4),
        "median_gap": round(float(np.median(gaps)), 4),
        "max_gap": round(float(np.max(gaps)), 4),
        "theoretical_bound": round(1 - 1 / np.e, 4),
        "cpsat_ms_median": round(
            float(np.median([float(r["cpsat_ms"]) for r in rows])), 1
        ),
        "rows": rows,
    }


def main() -> None:
    logging.basicConfig(level="INFO", format="%(asctime)s  %(message)s")
    report = run()

    print(
        f"\n{report['n_incidents']} incidents, held-out rings only "
        f"({', '.join(settings.holdout_ring_ids)})"
    )
    print(
        f"budget K={report['budget_k']}, innocence budget B={report['innocence_budget']}\n"
    )

    from app.eval.metrics import PolicySummary

    summaries = [PolicySummary(**s) for s in report["policies"]]  # type: ignore[arg-type]
    print(format_summary_table(summaries))

    gap = report["optimality_gap"]
    assert isinstance(gap, dict)
    if gap.get("n_incidents"):
        print(
            f"\nGreedy optimality gap vs CP-SAT over {gap['n_incidents']} incidents: "
            f"mean {float(gap['mean_gap']):.2%}, max {float(gap['max_gap']):.2%} "
            f"(worst-case bound allows {1 - float(gap['theoretical_bound']):.1%})"
        )

    print(f"\nWrote {settings.benchmark_path}")


if __name__ == "__main__":
    main()
