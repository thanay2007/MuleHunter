"""Account inspection: why this account, and what freezing it was worth."""

from __future__ import annotations

import polars as pl
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api import session
from app.config import settings
from app.detect.explain import attributions, marginal_recovery, phrase
from app.graphstore.build import DatasetMissingError
from app.graphstore.features import FEATURE_LABELS
from app.interdict.policies import plan_for

router = APIRouter()


class AttributionOut(BaseModel):
    feature: str
    label: str
    plain: str = Field(description="Plain-language phrasing for the drawer.")
    value: float
    shap: float
    population_median: float
    direction: str


class FeatureOut(BaseModel):
    feature: str
    label: str
    value: float
    population_median: float
    #: Signed deviation from the population, in robust standard deviations.
    deviation: float


class MarginalOut(BaseModel):
    in_plan: bool
    issued_at_minute: int | None
    saved_inr: float
    alternatives: list[dict[str, float]]


class AccountOut(BaseModel):
    account_id: str
    scenario_id: str
    bank_id: str
    district: str
    archetype: str
    kyc_tier: str
    open_date: str
    p_mule: float
    activity_weight: float
    tainted_held_inr: float
    tainted_through_inr: float
    first_seen_minute: int | None
    is_mule: bool
    ring_id: str
    layer_index: int
    is_cashout_node: bool
    attributions: list[AttributionOut]
    features: list[FeatureOut]
    marginal: MarginalOut
    rule_flags: list[str]


@router.get("/account/{account_id}", response_model=AccountOut)
def get_account(
    account_id: str,
    scenario_id: str = Query(..., description="Incident the account is viewed in"),
    budget_k: int = Query(default=settings.default_budget_k, ge=0, le=200),
    innocence_budget: float = Query(
        default=settings.default_innocence_budget, ge=0.0, le=50.0
    ),
) -> AccountOut:
    try:
        context = session.context_for_scenario(scenario_id)
    except DatasetMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"Unknown scenario {scenario_id}"
        ) from exc

    if account_id not in context.matrix.index:
        raise HTTPException(
            status_code=404,
            detail=f"{account_id} is not part of incident {scenario_id}",
        )

    dataset = session.dataset()
    meta = dataset.account_index.get(account_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown account {account_id}")

    detector = session.detector()
    found = attributions(detector, context.matrix, account_id, top_n=5)

    plan = plan_for("chakravyuh_greedy", context, budget_k, innocence_budget)
    in_plan = {step.account_id: step.issue_at_minute for step in plan.steps}

    marginal = _marginal(context, account_id, in_plan)
    first_seen = context.state.first_seen.get(account_id)

    return AccountOut(
        account_id=account_id,
        scenario_id=scenario_id,
        bank_id=str(meta["bank_id"]),
        district=str(meta["district"]),
        archetype=str(meta["archetype"]),
        kyc_tier=str(meta["kyc_tier"]),
        open_date=str(meta["open_date"]),
        p_mule=round(context.p_mule.get(account_id, 0.0), 4),
        activity_weight=round(context.activity_weight.get(account_id, 1.0), 3),
        tainted_held_inr=round(context.state.held.get(account_id, 0.0), 2),
        tainted_through_inr=round(context.state.through.get(account_id, 0.0), 2),
        first_seen_minute=(
            context.state.minute_of(first_seen) if first_seen is not None else None
        ),
        is_mule=bool(meta["is_mule"]) if meta["is_mule"] is not None else False,
        ring_id=str(meta["ring_id"] or ""),
        layer_index=(
            int(meta["layer_index"]) if meta["layer_index"] is not None else -1
        ),
        is_cashout_node=(
            bool(meta["is_cashout_node"]) if meta["is_cashout_node"] is not None else False
        ),
        attributions=[
            AttributionOut(
                feature=a.feature,
                label=a.label,
                plain=phrase(a),
                value=round(a.value, 4),
                shap=round(a.shap, 5),
                population_median=round(a.population_median, 4),
                direction=a.direction,
            )
            for a in found
        ],
        features=_feature_rows(context, account_id),
        marginal=marginal,
        rule_flags=_rule_flags(context, account_id),
    )


def _marginal(context, account_id: str, in_plan: dict[str, int]) -> MarginalOut:
    """What freezing this account saved, and what waiting would have cost."""
    issued = in_plan.get(account_id)
    # For an account outside the plan, ask the counterfactual anyway: what
    # would freezing it at the earliest possible moment have been worth? That
    # is what makes "why is this one not on the list" answerable.
    at = issued if issued is not None else context.rollouts.complaint_minute + 2

    result = marginal_recovery(
        context.rollouts, account_id, at, other_freezes=in_plan
    )
    return MarginalOut(
        in_plan=issued is not None,
        issued_at_minute=issued,
        saved_inr=result.saved_inr,
        alternatives=[
            {"minute": float(minute), "saved_inr": saved}
            for minute, saved in result.alternatives
        ],
    )


def _feature_rows(context, account_id: str) -> list[FeatureOut]:
    """Every feature against the population, for the diverging bar chart."""
    import numpy as np

    matrix = context.matrix
    row = matrix.row(account_id)
    medians = np.median(matrix.values, axis=0)
    # Median absolute deviation: robust to the long tails these features have,
    # where a standard deviation would be dominated by a handful of outliers.
    mad = np.median(np.abs(matrix.values - medians), axis=0)
    scale = np.maximum(mad * 1.4826, 1e-6)

    return [
        FeatureOut(
            feature=name,
            label=FEATURE_LABELS.get(name, name),
            value=round(float(row[i]), 4),
            population_median=round(float(medians[i]), 4),
            deviation=round(float(np.clip((row[i] - medians[i]) / scale[i], -6, 6)), 3),
        )
        for i, name in enumerate(matrix.names)
    ]


def _rule_flags(context, account_id: str) -> list[str]:
    from app.detect.baseline_rules import rule_reasons

    return rule_reasons(context.matrix, account_id)


class RingOut(BaseModel):
    ring_id: str
    accounts: int
    banks: list[str]
    districts: int
    device_clusters: int
    ip_clusters: int
    total_flow_inr: float
    cashout_capacity_inr: float
    mean_p_mule: float
    confidence: float
    dormancy_days_median: float
    members: list[str]


@router.get("/rings/{scenario_id}", response_model=list[RingOut])
def rings_for_scenario(scenario_id: str) -> list[RingOut]:
    """Rings discovered inside one incident, not across the whole dataset."""
    from app.detect.rings import detect_rings

    try:
        context = session.context_for_scenario(scenario_id)
    except DatasetMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"Unknown scenario {scenario_id}"
        ) from exc

    dataset = session.dataset()
    flagged = [
        account
        for account in context.candidates
        if context.p_mule.get(account, 0.0) >= settings.ring_cluster_threshold
    ]
    if len(flagged) < settings.min_ring_size:
        return []

    edges = (
        dataset.transactions.lazy()
        .filter(pl.col("timestamp") <= context.incident.complaint_time)
        .filter(
            pl.col("src").is_in(set(flagged)) | pl.col("dst").is_in(set(flagged))
        )
        .select("src", "dst", "amount", "timestamp", "channel")
        .collect()
    )
    discovered, _ = detect_rings(flagged, edges, context.p_mule, dataset)

    return [
        RingOut(
            ring_id=ring.ring_id,
            accounts=ring.size,
            banks=list(ring.banks),
            districts=ring.districts,
            device_clusters=ring.device_clusters,
            ip_clusters=ring.ip_clusters,
            total_flow_inr=ring.total_flow_inr,
            cashout_capacity_inr=ring.cashout_capacity_inr,
            mean_p_mule=ring.mean_p_mule,
            confidence=ring.confidence,
            dormancy_days_median=ring.dormancy_days_median,
            members=list(ring.accounts[:60]),
        )
        for ring in discovered
    ]
