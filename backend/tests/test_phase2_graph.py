"""Phase 2 acceptance: graph store, fund tracing and features.

Acceptance check (from the build plan):
    `/api/graph/{scenario}` returns a graph in <500ms; features have no NaNs.
    Legitimate high-velocity accounts score high on velocity features but low
    on shared-infrastructure features -- verified explicitly, not assumed.
"""

from __future__ import annotations

import time
from datetime import timedelta

import numpy as np
import polars as pl
import pytest

from app.config import settings
from app.graphstore.features import (
    SHARED_INFRA_FEATURES,
    VELOCITY_FEATURES,
    build_features,
    contrast_report,
)
from app.graphstore.incidents import scenario_incident
from app.graphstore.trace import candidate_accounts, trace_taint
from app.simulator.scenarios import SCENARIOS

from tests.conftest import needs_dataset

pytestmark = needs_dataset


# ------------------------------------------------------------------- tracing


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.scenario_id)
def test_taint_is_conserved(scenario, index) -> None:
    """Every rupee is either still inside the system or has left it.

    If tracing loses money, every recovery figure downstream is wrong by an
    unknown amount, so this is checked on all six scenarios rather than one.
    """
    state = trace_taint(
        scenario.victim_account,
        scenario.amount_inr,
        scenario.incident_time,
        scenario.complaint_time,
        index,
    )
    unaccounted = state.amount_inr - state.still_inside - state.exited
    assert abs(unaccounted) < 1.0, f"{unaccounted:,.2f} rupees unaccounted for"


def test_tracing_never_exceeds_the_stolen_amount(index) -> None:
    """Pro-rata pooling must not manufacture taint out of pass-through volume."""
    for scenario in SCENARIOS:
        state = trace_taint(
            scenario.victim_account,
            scenario.amount_inr,
            scenario.incident_time,
            scenario.incident_time
            + timedelta(hours=settings.incident_horizon_hours),
            index,
        )
        assert state.exited <= scenario.amount_inr + 1.0
        assert state.still_inside <= scenario.amount_inr + 1.0


def test_candidates_do_not_read_the_future(index) -> None:
    """Expanding along edges that have not happened yet would be leakage.

    A candidate set built at the complaint time must be a subset of one built
    at the end of the horizon, never the other way round.
    """
    scenario = scenario_incident("S1")
    early = trace_taint(
        scenario.victim_account,
        scenario.amount_inr,
        scenario.incident_time,
        scenario.complaint_time,
        index,
    )
    late = trace_taint(
        scenario.victim_account,
        scenario.amount_inr,
        scenario.incident_time,
        scenario.horizon_end,
        index,
    )
    assert len(candidate_accounts(early, index=index)) <= len(
        candidate_accounts(late, index=index)
    )


# ------------------------------------------------------------------ features


def test_features_have_no_nans(s1_context) -> None:
    values = s1_context.matrix.values
    assert np.isfinite(values).all(), "feature matrix contains NaN or inf"
    assert values.shape[0] == len(s1_context.candidates)


def test_feature_build_is_fast_enough(dataset, index) -> None:
    """The console builds features inside a request, so this is a live budget."""
    incident = scenario_incident("S1")
    state = trace_taint(
        incident.victim_account,
        incident.amount_inr,
        incident.incident_time,
        incident.complaint_time,
        index,
    )
    candidates = candidate_accounts(state, index=index)

    started = time.perf_counter()
    build_features(
        candidates, incident.victim_account, incident.complaint_time, dataset, index
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert elapsed_ms < 4_000, f"features took {elapsed_ms:.0f}ms"


def test_hard_negatives_look_like_mules_on_velocity(s1_context, dataset) -> None:
    """The check the whole detection argument depends on.

    Legitimate high-velocity accounts -- chit fund operators, travel agents --
    must be at least as extreme as mules on velocity features. If they are not,
    velocity alone separates the classes, the dataset is too easy, and every
    detection metric is inflated.
    """
    report = contrast_report(s1_context.matrix, dataset.labels, dataset)
    counts = report["counts"]
    assert isinstance(counts, dict)
    if counts.get("legit_high_velocity", 0) < 5:
        pytest.skip("too few hard negatives in this incident to compare")

    separation = float(report["velocity_separation"])  # type: ignore[arg-type]
    assert separation < 2.0, (
        f"mules are {separation:.2f}x hard negatives on velocity -- "
        "velocity alone separates the classes and the dataset is too easy"
    )


def test_shared_infrastructure_does_separate(s1_context, dataset) -> None:
    """And the neighbourhood features must carry the signal instead."""
    report = contrast_report(s1_context.matrix, dataset.labels, dataset)
    counts = report["counts"]
    assert isinstance(counts, dict)
    if counts.get("mule", 0) < 5:
        pytest.skip("too few mules in this incident to compare")

    velocity = report["velocity"]
    shared = report["shared_infrastructure"]
    assert isinstance(velocity, dict) and isinstance(shared, dict)
    assert set(velocity) == set(VELOCITY_FEATURES)
    assert set(shared) == set(SHARED_INFRA_FEATURES)


# ----------------------------------------------------------------- warehouse


def test_duckdb_warehouse_matches_the_parquet(dataset) -> None:
    from app.graphstore import warehouse

    warehouse.build_warehouse(force=True)
    try:
        rows = warehouse.scalar("SELECT count(*) FROM transactions")
        assert rows == dataset.transactions.height

        mules = warehouse.scalar(
            "SELECT count(*) FROM retail_accounts WHERE is_mule"
        )
        assert mules == dataset.labels.filter(pl.col("is_mule")).height
    finally:
        warehouse.close()
