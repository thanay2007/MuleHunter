"""Complaint intake on an arbitrary incident.

The point of this endpoint is that the six demo scenarios are not hardcoded
theatre, so the tests that matter are the ones proving a filed complaint runs
the *same* pipeline: it gets traced, it becomes addressable, and every route
that works for S1 works for it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.simulator.scenarios import SCENARIOS

from tests.conftest import needs_dataset

pytestmark = needs_dataset


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def complaint():
    scenario = SCENARIOS[0]
    return {
        "victim_account": scenario.victim_account,
        "amount_inr": 900_000,
        "incident_time": scenario.incident_time.isoformat(),
        "complaint_delay_minutes": 30,
        "channel": "IMPS",
    }


def test_intake_traces_a_filed_complaint(client, complaint) -> None:
    body = client.post("/api/intake", json=complaint).json()

    assert body["victim_bank"]
    assert body["accounts_traced"] > 0, "the money should have gone somewhere"
    assert body["candidates_considered"] > 0
    assert body["case_id"].startswith("CFMC")


def test_intake_is_addressable_everywhere_a_scenario_is(client, complaint) -> None:
    """A filed complaint must not be a second-class citizen.

    If any of these diverge, the intake form stops being evidence that the
    pipeline is general and becomes a separate code path that happens to
    return JSON.
    """
    incident_id = client.post("/api/intake", json=complaint).json()["incident_id"]

    plan = client.post(
        "/api/interdict",
        json={
            "scenario_id": incident_id,
            "policy": "chakravyuh_greedy",
            "budget_k": 25,
            "innocence_budget": 0.25,
            "adaptive_adversary": False,
        },
    )
    assert plan.status_code == 200
    assert plan.json()["plan"], "a traced complaint should yield instructions"

    graph = client.get(f"/api/graph/{incident_id}")
    assert graph.status_code == 200
    assert graph.json()["nodes"]

    order = client.get(f"/api/freeze-order/{incident_id}")
    assert order.status_code == 200
    assert order.json()["banks"]


def test_intake_is_deterministic(client, complaint) -> None:
    """The same complaint twice is the same incident, not a second one."""
    first = client.post("/api/intake", json=complaint).json()
    second = client.post("/api/intake", json=complaint).json()
    assert first["incident_id"] == second["incident_id"]
    assert first["case_id"] == second["case_id"]
    assert first["accounts_traced"] == second["accounts_traced"]


def test_intake_rejects_an_unknown_account(client, complaint) -> None:
    response = client.post(
        "/api/intake", json={**complaint, "victim_account": "AC999999"}
    )
    assert response.status_code == 404
    # The error has to be specific: typing a bad account is the likeliest
    # failure in front of an audience.
    assert "AC999999" in response.json()["detail"]


def test_intake_rejects_a_time_outside_the_dataset(client, complaint) -> None:
    response = client.post(
        "/api/intake", json={**complaint, "incident_time": "2020-01-01T10:00:00"}
    )
    assert response.status_code == 422
    assert "window" in response.json()["detail"].lower()


def test_intake_rejects_a_nonsense_amount(client, complaint) -> None:
    assert client.post("/api/intake", json={**complaint, "amount_inr": 0}).status_code == 422
    assert (
        client.post("/api/intake", json={**complaint, "amount_inr": -5}).status_code
        == 422
    )


def test_seeded_scenarios_still_resolve(client) -> None:
    """Registering intake incidents must not shadow the seeded six."""
    assert client.get("/api/graph/S1").status_code == 200
    assert client.get("/api/freeze-order/S1").status_code == 200
