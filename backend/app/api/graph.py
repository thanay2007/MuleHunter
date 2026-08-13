"""Incident subgraph and ring summaries."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


class LinkOut(BaseModel):
    source: str
    target: str
    amount: float
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
        graph = build_incident_graph(scenario_id)
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
        # demo looks the same on stage as it did in rehearsal.
        layout_seed=abs(hash(scenario_id)) % 100_000,
        truncated=graph.truncated,
        fraud_flow_inr=round(graph.total_laundered, 2),
        nodes=[NodeOut(id=n.account_id, **_node_fields(n)) for n in graph.nodes],
        links=[LinkOut(**vars(link)) for link in graph.links],
    )


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
