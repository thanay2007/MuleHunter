"""The interdiction endpoint: compute a freeze plan and score it honestly.

`POST /api/interdict` returns the plan contract, plus what the plan actually
achieved when replayed against the real timeline and what a do-nothing
baseline would have produced. Those three together are the whole argument, and
returning them from one call means the console cannot show a projection next to
an outcome from a different computation.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api import session
from app.config import settings
from app.detect.explain import reason_codes
from app.graphstore.build import DatasetMissingError
from app.interdict.greedy import FreezePlan
from app.interdict.policies import POLICIES, POLICY_LABELS, plan_for
from app.interdict.replay import replay

log = logging.getLogger(__name__)
router = APIRouter()


class InterdictRequest(BaseModel):
    scenario_id: str
    policy: str = "chakravyuh_greedy"
    budget_k: int = Field(default=settings.default_budget_k, ge=0, le=200)
    innocence_budget: float = Field(
        default=settings.default_innocence_budget, ge=0.0, le=50.0
    )
    adaptive_adversary: bool = Field(
        default=False,
        description=(
            "Model an operator who reroutes blocked money instead of giving up."
        ),
    )


class PlanStepOut(BaseModel):
    rank: int
    account_id: str
    bank: str
    issue_at_minute: int
    action: str
    marginal_recovery_inr: float
    p_mule: float
    innocence_cost: float
    effectiveness: float
    reason_codes: list[str]
    is_mule: bool = Field(
        description="Ground truth. Shown so the freeze list can be audited."
    )


class OutcomeOut(BaseModel):
    """What actually happened, replayed against the recorded timeline."""

    prevented_inr: float = Field(
        description="Rupees kept inside the banking system that would have left."
    )
    leaked_inr: float
    secured_inr: float
    residual_inr: float
    already_gone_inr: float
    innocent_frozen: int
    mules_frozen: int
    blocked_transfers: int
    rerouted_transfers: int


class InterdictResponse(BaseModel):
    scenario_id: str
    policy: str
    policy_label: str
    budget_k: int
    innocence_budget: float
    #: Echoed back so the console can caption a result with the adversary it was
    #: actually scored against, rather than with whatever the checkbox says by
    #: the time the response lands.
    adaptive_adversary: bool

    plan: list[PlanStepOut]
    projected_recovery_inr: float
    projected_leak_inr: float
    projected_secured_inr: float
    innocent_accounts_frozen_expected: float
    total_innocence_cost: float
    solve_ms: float

    outcome: OutcomeOut
    do_nothing_leak_inr: float
    amount_inr: float
    complaint_minute: int
    horizon_minutes: int
    candidates_considered: int
    rollouts: int
    particles: int


@router.post("/interdict", response_model=InterdictResponse)
def interdict(request: InterdictRequest) -> InterdictResponse:
    if request.policy not in POLICIES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown policy {request.policy!r}. Expected one of {list(POLICIES)}.",
        )

    try:
        context = session.context_for_scenario(request.scenario_id)
    except DatasetMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"Unknown scenario {request.scenario_id}"
        ) from exc

    plan = plan_for(
        request.policy, context, request.budget_k, request.innocence_budget
    )

    horizon = settings.incident_horizon_hours * 60
    mules = session.dataset().mule_ids
    reroute = settings.adversary_reroute_prob if request.adaptive_adversary else 0.0

    outcome = replay(
        context.state, plan, horizon, mules, session.index(), reroute_prob=reroute
    )
    nothing = replay(
        context.state,
        FreezePlan(),
        horizon,
        mules,
        session.index(),
        reroute_prob=reroute,
    )

    return InterdictResponse(
        scenario_id=request.scenario_id,
        policy=request.policy,
        policy_label=POLICY_LABELS.get(request.policy, request.policy),
        budget_k=request.budget_k,
        innocence_budget=request.innocence_budget,
        adaptive_adversary=request.adaptive_adversary,
        plan=_plan_out(plan, context, mules),
        projected_recovery_inr=plan.projected_recovery_inr,
        projected_leak_inr=plan.projected_leak_inr,
        projected_secured_inr=plan.projected_secured_inr,
        innocent_accounts_frozen_expected=plan.innocent_accounts_frozen_expected,
        total_innocence_cost=plan.total_innocence_cost,
        solve_ms=round(plan.solve_ms, 2),
        outcome=OutcomeOut(
            prevented_inr=round(
                max(0.0, nothing.leaked_inr - outcome.leaked_inr), 2
            ),
            leaked_inr=outcome.leaked_inr,
            secured_inr=outcome.recovered_inr,
            residual_inr=outcome.residual_inr,
            already_gone_inr=outcome.already_gone_inr,
            innocent_frozen=outcome.innocent_frozen,
            mules_frozen=outcome.mules_frozen,
            blocked_transfers=outcome.blocked_transfers,
            rerouted_transfers=outcome.rerouted_transfers,
        ),
        do_nothing_leak_inr=nothing.leaked_inr,
        amount_inr=context.incident.amount_inr,
        complaint_minute=context.rollouts.complaint_minute,
        horizon_minutes=horizon,
        candidates_considered=len(context.candidates),
        rollouts=context.rollouts.n_rollouts,
        particles=len(context.rollouts.particles),
    )


def _plan_out(plan: FreezePlan, context, mules: frozenset[str]) -> list[PlanStepOut]:
    banks = _bank_lookup(context)
    detector = session.detector()

    out: list[PlanStepOut] = []
    for step in plan.steps:
        out.append(
            PlanStepOut(
                rank=step.rank,
                account_id=step.account_id,
                bank=banks.get(step.account_id, "—"),
                issue_at_minute=step.issue_at_minute,
                action=step.action,
                marginal_recovery_inr=step.marginal_recovery_inr,
                p_mule=step.p_mule,
                innocence_cost=step.innocence_cost,
                effectiveness=step.effectiveness,
                reason_codes=_reason_codes(detector, context, step.account_id),
                is_mule=step.account_id in mules,
            )
        )
    return out


def _bank_lookup(context) -> dict[str, str]:
    import polars as pl

    rows = session.dataset().accounts.filter(
        pl.col("account_id").is_in(set(context.candidates))
    )
    return dict(zip(rows["account_id"].to_list(), rows["bank_id"].to_list()))


def _reason_codes(detector, context, account_id: str) -> list[str]:
    """The two or three strongest reasons, in plain language."""
    return reason_codes(detector, context.matrix, account_id)


@router.get("/policies")
def list_policies() -> list[dict[str, str]]:
    return [
        {"policy": policy, "label": POLICY_LABELS[policy]} for policy in POLICIES
    ]
