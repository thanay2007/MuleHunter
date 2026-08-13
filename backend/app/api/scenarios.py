"""Scenario catalogue and dataset overview."""

from __future__ import annotations

from datetime import datetime

import polars as pl
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.graphstore.build import (
    DatasetMissingError,
    dataset_summary,
    load_dataset,
)
from app.simulator.scenarios import SCENARIOS

router = APIRouter()


class ScenarioOut(BaseModel):
    scenario_id: str
    name: str
    summary: str
    victim_account: str
    victim_district: str
    victim_archetype: str
    amount_inr: float
    complaint_delay_minutes: int
    ring_id: str
    ring_typology: str
    secondary_ring_id: str | None
    incident_time: datetime
    complaint_time: datetime
    # Realised from the data rather than declared, so the card cannot drift
    # from what the simulator actually produced.
    ring_accounts: int = Field(description="Accounts in the target ring")
    episode_flow_inr: float = Field(
        description=(
            "Total value of fraud transfers observed in the window. Money is "
            "counted once per hop, so this exceeds the stolen amount by design "
            "-- it measures laundering activity, not losses."
        )
    )
    hops: int = Field(description="Deepest layer index in the target ring")


class ArchetypeCount(BaseModel):
    name: str
    count: int


class HourCount(BaseModel):
    hour: int
    count: int


class DatasetSummaryOut(BaseModel):
    accounts: int
    exit_nodes: int
    transactions: int
    fraud_transactions: int
    mule_accounts: int
    mule_prevalence: float
    banks: int
    districts: int
    total_laundered_inr: float
    archetypes: list[ArchetypeCount]
    channels: list[ArchetypeCount]
    hourly: list[HourCount]


@router.get("/scenarios", response_model=list[ScenarioOut])
def list_scenarios() -> list[ScenarioOut]:
    try:
        dataset = load_dataset()
    except DatasetMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    labels = dataset.labels
    fraud = dataset.transactions.filter(pl.col("is_fraud"))

    out: list[ScenarioOut] = []
    for scenario in SCENARIOS:
        members = labels.filter(pl.col("ring_id") == scenario.ring_id)
        episode = fraud.filter(
            (pl.col("timestamp") >= scenario.incident_time)
            & (pl.col("timestamp") <= scenario.complaint_time)
            & (pl.col("ring_id").is_in([scenario.ring_id, scenario.secondary_ring_id or ""]))
        )

        out.append(
            ScenarioOut(
                scenario_id=scenario.scenario_id,
                name=scenario.name,
                summary=scenario.summary,
                victim_account=scenario.victim_account,
                victim_district=scenario.victim_district,
                victim_archetype=scenario.victim_archetype,
                amount_inr=scenario.amount_inr,
                complaint_delay_minutes=scenario.complaint_delay_minutes,
                ring_id=scenario.ring_id,
                ring_typology=scenario.ring_typology,
                secondary_ring_id=scenario.secondary_ring_id,
                incident_time=scenario.incident_time,
                complaint_time=scenario.complaint_time,
                ring_accounts=members.height,
                episode_flow_inr=round(float(episode["amount"].sum() or 0.0), 2),
                hops=int(members["layer_index"].max() or 0),
            )
        )
    return out


@router.get("/dataset/summary", response_model=DatasetSummaryOut)
def get_dataset_summary() -> DatasetSummaryOut:
    try:
        return DatasetSummaryOut(**dataset_summary())  # type: ignore[arg-type]
    except DatasetMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
