"""The four policies, so the comparison is honest.

1. `named_account_only` -- freeze the one account named in the complaint. This
   is what happens today: the victim reports "I sent ₹15,00,000 to this
   account", that account is frozen, and by then the money is four layers away.
2. `top_k_classifier` -- freeze the K highest-scoring accounts. What a good ML
   project produces, and it is genuinely better than (1). Its weakness is that
   suspicion and *rupees at stake* are different quantities: it will happily
   spend the whole budget on deep-layer mules holding ₹8,000 each while a
   collector holding ₹4,00,000 goes untouched.
3. `one_hop_downstream` -- freeze everything one hop from the named account.
   What a panicked bank does. Catches money, and freezes a great many innocent
   people to do it.
4. `chakravyuh_greedy` -- the freeze-frontier solver.

All four produce the same `FreezePlan` type and are scored by the same replay
against the same real timeline, under the same budgets. Policy 1 is given the
same authority as policy 4 and simply cannot use it, which is the point.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from app.config import settings
from app.detect.gbdt import Detector, load_detector
from app.graphstore.build import Dataset, load_dataset
from app.graphstore.features import FeatureMatrix, build_features
from app.graphstore.incidents import Incident
from app.graphstore.trace import (
    TaintState,
    TransactionIndex,
    candidate_accounts,
    trace_taint,
    transaction_index,
)
from app.interdict import greedy
from app.interdict.greedy import FreezePlan, FreezeStep, issue_minute
from app.interdict.propagate import RolloutSet, fit_behaviour, run_rollouts

log = logging.getLogger(__name__)

POLICIES: tuple[str, ...] = (
    "named_account_only",
    "top_k_classifier",
    "one_hop_downstream",
    "chakravyuh_greedy",
)

POLICY_LABELS: dict[str, str] = {
    "named_account_only": "Current practice — freeze the named account",
    "top_k_classifier": "Top-K classifier — freeze the most suspicious",
    "one_hop_downstream": "One hop downstream — freeze everything adjacent",
    "chakravyuh_greedy": "Chakravyuh — freeze frontier",
}


@dataclass
class IncidentContext:
    """Everything computed once per incident and shared by every policy.

    Built once so that a four-policy comparison does not re-trace, re-featurise
    and re-score four times -- and, more importantly, so every policy is
    reasoning from byte-identical inputs.
    """

    incident: Incident
    state: TaintState
    candidates: list[str]
    matrix: FeatureMatrix
    p_mule: dict[str, float]
    activity_weight: dict[str, float]
    rollouts: RolloutSet

    @property
    def named_account(self) -> str | None:
        """The account the victim actually named -- the first hop of the money."""
        first = [
            flow.dst
            for flow in self.state.flows
            if flow.src == self.incident.victim_account
        ]
        return first[0] if first else None


def build_context(
    incident: Incident,
    dataset: Dataset | None = None,
    index: TransactionIndex | None = None,
    detector: Detector | None = None,
    n_rollouts: int | None = None,
) -> IncidentContext:
    """Trace, score and forecast one incident, ready for any policy."""
    ds = dataset if dataset is not None else load_dataset()
    idx = index if index is not None else transaction_index()
    model = detector if detector is not None else load_detector()

    state = trace_taint(
        incident.victim_account,
        incident.amount_inr,
        incident.incident_time,
        incident.complaint_time,
        idx,
    )
    candidates = candidate_accounts(state, index=idx)
    matrix = build_features(
        candidates, incident.victim_account, incident.complaint_time, ds, idx
    )

    if model is not None and candidates:
        scores = model.score(matrix)
    else:
        # No trained model: fall back to the rules tier so the system still
        # runs. Documented behaviour, not a silent degradation.
        from app.detect.baseline_rules import rule_scores

        scores = rule_scores(matrix) * 0.9 if candidates else np.zeros(0)

    p_mule = {a: float(s) for a, s in zip(candidates, scores)}
    behaviour = fit_behaviour(candidates, incident.complaint_time, ds, idx)
    rollouts = run_rollouts(
        state,
        behaviour,
        incident.incident_id,
        n_rollouts=n_rollouts,
        index=idx,
    )

    return IncidentContext(
        incident=incident,
        state=state,
        candidates=candidates,
        matrix=matrix,
        p_mule=p_mule,
        activity_weight=_activity_weights(matrix),
        rollouts=rollouts,
    )


def _activity_weights(matrix: FeatureMatrix) -> dict[str, float]:
    """How much of a real financial life sits behind each account.

    Freezing an account nobody uses is an inconvenience. Freezing the one a
    household's salary lands in is a serious harm, and the cost function has to
    tell them apart or the innocence budget prices every mistake the same.
    """
    if not matrix.account_ids:
        return {}

    columns = {name: i for i, name in enumerate(matrix.names)}
    age = matrix.values[:, columns["account_age_days"]]
    counterparties = matrix.values[:, columns["in_degree"]]
    volume = matrix.values[:, columns["log_total_out"]]

    def normalise(column: np.ndarray) -> np.ndarray:
        top = np.percentile(column, 95) if column.size else 1.0
        return np.clip(column / max(top, 1e-6), 0.0, 1.0)

    weight = (
        0.4 * normalise(age) + 0.35 * normalise(counterparties) + 0.25 * normalise(volume)
    )
    return {
        account: float(0.25 + 0.75 * w)
        for account, w in zip(matrix.account_ids, weight)
    }


# ---------------------------------------------------------------------------
# policies
# ---------------------------------------------------------------------------


def plan_for(
    policy: str,
    context: IncidentContext,
    budget_k: int | None = None,
    innocence_budget: float | None = None,
) -> FreezePlan:
    """Produce a freeze plan under the named policy."""
    k = budget_k if budget_k is not None else settings.default_budget_k
    budget = (
        innocence_budget
        if innocence_budget is not None
        else settings.default_innocence_budget
    )

    if policy == "chakravyuh_greedy":
        return greedy.solve(
            context.rollouts, context.p_mule, context.activity_weight, k, budget
        )
    if policy == "named_account_only":
        return _named_account_only(context)
    if policy == "top_k_classifier":
        return _top_k(context, k)
    if policy == "one_hop_downstream":
        return _one_hop(context, k)
    raise ValueError(f"Unknown policy {policy!r}")


def _as_plan(context: IncidentContext, accounts: list[str]) -> FreezePlan:
    """Wrap a chosen account list in the shared plan format.

    Baselines always issue a full freeze -- graded response is a capability of
    the solver, not of the comparison, and pretending otherwise would hand the
    baselines an advantage they do not have in practice.
    """
    plan = FreezePlan()
    complaint = context.rollouts.complaint_minute

    for rank, account in enumerate(accounts):
        p = context.p_mule.get(account, 0.0)
        plan.steps.append(
            FreezeStep(
                rank=rank + 1,
                account_id=account,
                action="full_freeze",
                issue_at_minute=issue_minute(rank, complaint),
                marginal_recovery_inr=0.0,
                p_mule=round(p, 4),
                innocence_cost=round(
                    greedy.innocence_cost(
                        p, context.activity_weight.get(account, 1.0), "full_freeze"
                    ),
                    4,
                ),
                effectiveness=settings.action_effectiveness["full_freeze"],
            )
        )

    plan.total_innocence_cost = round(
        sum(step.innocence_cost for step in plan.steps), 4
    )
    plan.innocent_accounts_frozen_expected = round(
        sum(1.0 - step.p_mule for step in plan.steps), 3
    )
    return plan


def _named_account_only(context: IncidentContext) -> FreezePlan:
    named = context.named_account
    return _as_plan(context, [named] if named else [])


def _top_k(context: IncidentContext, k: int) -> FreezePlan:
    ranked = sorted(
        context.p_mule.items(), key=lambda item: (-item[1], item[0])
    )
    return _as_plan(context, [account for account, _ in ranked[:k]])


def _one_hop(context: IncidentContext, k: int) -> FreezePlan:
    """Everything the named account paid, up to the budget.

    Ordered by value received, because a bank doing this by hand would work
    down the statement from the largest transfer.
    """
    named = context.named_account
    if named is None:
        return _as_plan(context, [])

    downstream: dict[str, float] = {}
    for flow in context.state.flows:
        if flow.src == named:
            downstream[flow.dst] = downstream.get(flow.dst, 0.0) + flow.tainted

    ranked = sorted(downstream.items(), key=lambda item: (-item[1], item[0]))
    accounts = [named] + [
        account
        for account, _ in ranked
        if account != named and account in context.p_mule
    ]
    return _as_plan(context, accounts[:k])
