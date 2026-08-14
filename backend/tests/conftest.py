"""Shared fixtures.

The generated dataset is built once per test session and reused. Regenerating
it per test would be correct and unbearably slow; the generator has its own
determinism tests in `test_phase1.py`, so reuse here is safe.
"""

from __future__ import annotations

import pytest

from app.config import settings


def _dataset_available() -> bool:
    return all(
        path.exists()
        for path in (
            settings.accounts_path,
            settings.transactions_path,
            settings.labels_path,
            settings.episodes_path,
        )
    )


needs_dataset = pytest.mark.skipif(
    not _dataset_available(),
    reason="dataset not generated -- run: python -m app.simulator.generator",
)

needs_detector = pytest.mark.skipif(
    not settings.detector_path.exists(),
    reason="detector not trained -- run: python -m app.detect.train",
)


@pytest.fixture(scope="session")
def dataset():
    from app.graphstore.build import load_dataset

    return load_dataset()


@pytest.fixture(scope="session")
def index():
    from app.graphstore.trace import transaction_index

    return transaction_index()


@pytest.fixture(scope="session")
def detector():
    from app.detect.gbdt import load_detector

    return load_detector()


@pytest.fixture(scope="session")
def s1_context(dataset, index, detector):
    """The stage demo incident, built once."""
    from app.graphstore.incidents import scenario_incident
    from app.interdict.policies import build_context

    return build_context(scenario_incident("S1"), dataset, index, detector)
