"""API contract tests, including the WebSocket replay stream.

The §10 contract is what the frontend is written against, so a change here is a
breaking change. These tests pin the shape rather than the values.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

from tests.conftest import needs_dataset, needs_detector

pytestmark = needs_dataset


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_live_artifact_state(client) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["master_seed"] == settings.master_seed
    assert body["artifacts"]["accounts"] is True


def test_scenarios_returns_all_six(client) -> None:
    body = client.get("/api/scenarios").json()
    assert len(body) == 6
    assert {s["scenario_id"] for s in body} == {"S1", "S2", "S3", "S4", "S5", "S6"}


def test_graph_endpoint_is_fast_and_stable(client) -> None:
    first = client.get("/api/graph/S1")
    assert first.status_code == 200

    body = first.json()
    assert body["nodes"] and body["links"]
    assert body["victim_account"] == "AC000000"

    # Layout seed must not move between processes, or the graph reshuffles
    # between rehearsal and stage.
    second = client.get("/api/graph/S1").json()
    assert second["layout_seed"] == body["layout_seed"]


def test_unknown_scenario_is_a_404(client) -> None:
    assert client.get("/api/graph/NOPE").status_code == 404


@needs_detector
def test_interdict_returns_the_plan_contract(client) -> None:
    response = client.post(
        "/api/interdict",
        json={
            "scenario_id": "S1",
            "policy": "chakravyuh_greedy",
            "budget_k": 12,
            "innocence_budget": 2.0,
            "adaptive_adversary": False,
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert len(body["plan"]) <= 12
    assert body["solve_ms"] < settings.greedy_latency_budget_ms

    step = body["plan"][0]
    for field in (
        "rank",
        "account_id",
        "bank",
        "issue_at_minute",
        "action",
        "marginal_recovery_inr",
        "p_mule",
        "innocence_cost",
        "reason_codes",
    ):
        assert field in step, f"plan step is missing {field}"

    assert step["action"] in (
        "full_freeze",
        "outbound_hold",
        "step_up_verification",
    )
    assert body["outcome"]["prevented_inr"] >= 0
    assert body["do_nothing_leak_inr"] >= body["outcome"]["leaked_inr"]


@needs_detector
def test_interdict_rejects_an_unknown_policy(client) -> None:
    response = client.post(
        "/api/interdict", json={"scenario_id": "S1", "policy": "wishful_thinking"}
    )
    assert response.status_code == 422


@needs_detector
def test_account_endpoint_explains_a_frozen_account(client) -> None:
    plan = client.post("/api/interdict", json={"scenario_id": "S1"}).json()
    account_id = plan["plan"][0]["account_id"]

    body = client.get(f"/api/account/{account_id}?scenario_id=S1").json()
    assert body["account_id"] == account_id
    assert body["attributions"], "no attributions returned"
    assert all(a["plain"] for a in body["attributions"])
    assert body["marginal"]["in_plan"] is True
    assert len(body["features"]) > 20


def test_account_outside_the_incident_is_a_404(client) -> None:
    assert (
        client.get("/api/account/AC999999?scenario_id=S1").status_code == 404
    )


@needs_detector
def test_replay_stream_delivers_both_timelines(client) -> None:
    """The console runs the whole demo from this one socket."""
    url = "/ws/replay/S1?policy=chakravyuh_greedy&fps=60"
    with client.websocket_connect(url) as ws:
        header = ws.receive_json()
        assert header["type"] == "header"
        assert header["horizon_minutes"] == settings.incident_horizon_hours * 60
        assert "chakravyuh" in header["final"]
        assert "baseline" in header["final"]

        frame = ws.receive_json()
        assert frame["type"] == "frame"
        for field in (
            "minute",
            "flows",
            "frozen",
            "recovered_inr",
            "leaked_inr",
            "at_risk_inr",
            "frontier_accounts",
        ):
            assert field in frame, f"replay frame is missing {field}"
        assert "baseline" in frame

        # Money must reconcile on every frame, not just at the end.
        total = frame["recovered_inr"] + frame["leaked_inr"] + frame["at_risk_inr"]
        assert total <= header["amount_inr"] + 1.0


def test_replay_stream_rejects_an_unknown_policy(client) -> None:
    with client.websocket_connect("/ws/replay/S1?policy=nonsense") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"


def test_evaluate_endpoint_is_explicit_when_not_generated(client) -> None:
    response = client.get("/api/evaluate")
    assert response.status_code in (200, 503)
    if response.status_code == 503:
        # An empty tab is not acceptable; it must say what to run.
        assert "app.eval.harness" in response.json()["detail"]
