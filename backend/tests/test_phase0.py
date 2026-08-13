"""Phase 0 acceptance: the app boots and serves live health data.

Acceptance check (from the build plan):
    `make dev` opens a page that reads live data from /api/health.

The frontend half of that is verified by eye; this file locks down the
backend half so the contract the page depends on cannot silently drift.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "chakravyuh"


def test_health_reports_live_values_not_placeholders() -> None:
    """The page must read *live* data, so health has to reflect real state."""
    body = client.get("/api/health").json()

    # Version and phase come from config, not from a literal in the route.
    assert body["version"] == settings.version
    assert body["phase"] == settings.phase

    # uptime_seconds is computed at request time and must be a real number.
    assert isinstance(body["uptime_seconds"], float)
    assert body["uptime_seconds"] >= 0.0

    # The data-readiness flags tell the UI which phases have produced output.
    for key in ("accounts", "transactions", "labels", "benchmark"):
        assert key in body["artifacts"]
        assert isinstance(body["artifacts"][key], bool)


def test_health_uptime_advances() -> None:
    first = client.get("/api/health").json()["uptime_seconds"]
    second = client.get("/api/health").json()["uptime_seconds"]
    assert second >= first


def test_seed_is_pinned_for_reproducible_demos() -> None:
    """A demo that changes between rehearsal and stage is a lost hackathon."""
    assert settings.master_seed == 20260814
    assert client.get("/api/health").json()["master_seed"] == settings.master_seed


def test_openapi_schema_builds() -> None:
    """Catches malformed Pydantic models across every router early."""
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert "/api/health" in schema.json()["paths"]
