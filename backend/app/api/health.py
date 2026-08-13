"""Health and readiness.

This route is not decoration -- the frontend reads it on load to decide which
phases have produced artifacts, so it must report live state rather than a
hardcoded literal.
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter()

_STARTED_AT: float = time.monotonic()


class ArtifactStatus(BaseModel):
    """Which generated artifacts exist on disk right now."""

    accounts: bool = Field(description="data/accounts.parquet (phase 1)")
    transactions: bool = Field(description="data/transactions.parquet (phase 1)")
    labels: bool = Field(description="data/labels.parquet (phase 1)")
    warehouse: bool = Field(description="data/chakravyuh.duckdb (phase 2)")
    benchmark: bool = Field(description="data/benchmark.json (phase 6)")


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    phase: int = Field(description="Highest completed build phase.")
    uptime_seconds: float
    master_seed: int = Field(
        description="Pinned RNG seed. Identical across runs by design."
    )
    artifacts: ArtifactStatus


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=settings.version,
        phase=settings.phase,
        uptime_seconds=round(time.monotonic() - _STARTED_AT, 3),
        master_seed=settings.master_seed,
        artifacts=ArtifactStatus(
            accounts=settings.accounts_path.exists(),
            transactions=settings.transactions_path.exists(),
            labels=settings.labels_path.exists(),
            warehouse=settings.duckdb_path.exists(),
            benchmark=settings.benchmark_path.exists(),
        ),
    )
