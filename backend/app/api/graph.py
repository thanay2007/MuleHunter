"""Incident subgraph and ring summaries."""

from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api import session
from app.graphstore.build import (
    DatasetMissingError,
    build_incident_graph,
    ring_summaries,
)

router = APIRouter()


class NodeOut(BaseModel):
    id: str
    kind: str
    bank_id: str
    district: str
    archetype: str
    is_mule: bool
    ring_id: str
    layer_index: int
    is_cashout_node: bool
    exit_kind: str
    depth: int
    first_seen_minute: int
    amount_in: float
    amount_out: float
    tainted_in: float


class LinkOut(BaseModel):
    source: str
    target: str
    amount: float
    tainted: float = Field(
        description="How much of this transfer was the victim's money."
    )
    minute: int
    channel: str
    is_fraud: bool


class GraphOut(BaseModel):
    scenario_id: str
    victim_account: str
    incident_time: datetime
    horizon_minutes: int
    layout_seed: int
    truncated: bool
    fraud_flow_inr: float
    """Value of fraud transfers in the window, counted once per hop."""
    nodes: list[NodeOut]
    links: list[LinkOut]


class RingOut(BaseModel):
    ring_id: str
    typology: str
    accounts: int
    banks: list[str]
    districts: int
    device_clusters: int
    max_layer: int
    cashout_nodes: int
    total_flow_inr: float
    txn_count: int
    dormancy_days: int


@router.get("/graph/{scenario_id}", response_model=GraphOut)
def get_graph(scenario_id: str) -> GraphOut:
    try:
        # Resolve through the session so a complaint filed at intake draws its
        # canvas from the same builder as a seeded scenario.
        incident = session.incident_for(scenario_id)
        graph = build_incident_graph(
            scenario_id,
            victim_account=incident.victim_account,
            amount_inr=incident.amount_inr,
            incident_time=incident.incident_time,
        )
    except DatasetMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown scenario {scenario_id}") from exc

    return GraphOut(
        scenario_id=graph.scenario_id,
        victim_account=graph.victim_account,
        incident_time=graph.incident_time,
        horizon_minutes=graph.horizon_minutes,
        # Fixed layout seed: the graph must settle identically every run so the
        # demo looks the same on stage as it did in rehearsal. `hash()` on a str
        # is salted per process, so it is useless here -- the digest is stable.
        layout_seed=_stable_seed(scenario_id),
        truncated=graph.truncated,
        fraud_flow_inr=round(graph.total_laundered, 2),
        nodes=[NodeOut(id=n.account_id, **_node_fields(n)) for n in graph.nodes],
        links=[LinkOut(**vars(link)) for link in graph.links],
    )


def _stable_seed(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16) % 100_000


def _node_fields(node: object) -> dict[str, object]:
    fields = dict(vars(node))
    fields.pop("account_id", None)
    return fields


@router.get("/rings", response_model=list[RingOut])
def get_rings() -> list[RingOut]:
    try:
        return [RingOut(**r) for r in ring_summaries()]  # type: ignore[arg-type]
    except DatasetMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
