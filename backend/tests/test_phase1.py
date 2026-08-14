"""Phase 1 acceptance: the transaction simulator.

Acceptance check (from the build plan):
    Generates 250k transactions / 40k accounts in <60s, with 12 injected
    rings; label file validates. Regenerating with the same seed produces
    byte-identical files.

The generator is a first-class deliverable, not a fixture -- if the data is
not defensible then nothing downstream is, so these tests are strict.
"""

from __future__ import annotations

import hashlib
import time
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

from app.config import settings
from app.simulator.generator import GeneratedDataset, generate_dataset

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> GeneratedDataset:
    out = tmp_path_factory.mktemp("gen1")
    return generate_dataset(out_dir=out)


# --------------------------------------------------------------- scale & speed


def test_generates_target_volume_within_time_budget(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    out = tmp_path_factory.mktemp("timed")
    started = time.perf_counter()
    ds = generate_dataset(out_dir=out)
    elapsed = time.perf_counter() - started

    assert elapsed < 60.0, f"generation took {elapsed:.1f}s, budget is 60s"

    # Retail account population is exact.
    retail = ds.accounts.filter(pl.col("archetype") != "exit_point")
    assert retail.height == settings.n_accounts

    # The acceptance bar is 250k transactions. `target_transactions` sizes the
    # *background* layer only -- pass-through sweeps and ring episodes are
    # generated on top of it, so the emitted dataset is roughly a third larger.
    assert ds.transactions.height >= 250_000, (
        f"only {ds.transactions.height:,} transactions; the bar is 250,000"
    )
    assert ds.transactions.height <= settings.target_transactions * 2.5, (
        "dataset is far larger than the background target implies -- check the "
        "pass-through layer has not run away"
    )


# ------------------------------------------------------------------- integrity


def test_all_files_written(dataset: GeneratedDataset) -> None:
    for name in ("accounts.parquet", "transactions.parquet", "labels.parquet", "summary.md"):
        path = dataset.out_dir / name
        assert path.exists(), f"{name} was not written"
        assert path.stat().st_size > 0


def test_no_nulls_anywhere(dataset: GeneratedDataset) -> None:
    """A null in the source data becomes a NaN in the feature matrix later."""
    for name, frame in (
        ("accounts", dataset.accounts),
        ("transactions", dataset.transactions),
        ("labels", dataset.labels),
    ):
        counts = frame.null_count().row(0)
        assert sum(counts) == 0, f"{name} has nulls: {dict(zip(frame.columns, counts))}"


def test_referential_integrity(dataset: GeneratedDataset) -> None:
    """Every transaction endpoint must be a real node in the account table."""
    known = set(dataset.accounts["account_id"].to_list())
    assert set(dataset.transactions["src"].to_list()) <= known
    assert set(dataset.transactions["dst"].to_list()) <= known

    # Labels cover exactly the retail population.
    retail = set(
        dataset.accounts.filter(pl.col("archetype") != "exit_point")["account_id"].to_list()
    )
    assert set(dataset.labels["account_id"].to_list()) == retail


def test_no_self_transfers(dataset: GeneratedDataset) -> None:
    assert dataset.transactions.filter(pl.col("src") == pl.col("dst")).height == 0


def test_amounts_and_timestamps_are_sane(dataset: GeneratedDataset) -> None:
    amounts = dataset.transactions["amount"]
    assert amounts.min() > 0
    assert amounts.max() < 5e7  # nothing absurd

    ts = dataset.transactions["timestamp"]
    span_days = (ts.max() - ts.min()).total_seconds() / 86400.0
    assert span_days <= settings.sim_days + 1


def test_transactions_sorted_deterministically(dataset: GeneratedDataset) -> None:
    """Stable ordering is a precondition for byte-identical output."""
    ts = dataset.transactions["timestamp"].to_list()
    assert ts == sorted(ts)


# ----------------------------------------------------------------------- rings


def test_twelve_rings_with_all_four_typologies(dataset: GeneratedDataset) -> None:
    assert len(dataset.rings) == settings.n_rings

    typologies = [r.typology for r in dataset.rings]
    for expected in ("fanout", "chain_burst", "structuring", "crypto_exit"):
        assert typologies.count(expected) == 3, f"expected 3 {expected} rings"


def test_labels_validate(dataset: GeneratedDataset) -> None:
    labels = dataset.labels

    mules = labels.filter(pl.col("is_mule"))
    assert mules.height > 0

    # Every mule belongs to a ring; every non-mule does not.
    assert mules.filter(pl.col("ring_id") == "").height == 0
    assert labels.filter(~pl.col("is_mule")).filter(pl.col("ring_id") != "").height == 0

    # layer_index is -1 for non-mules and >= 0 for mules.
    assert mules.filter(pl.col("layer_index") < 0).height == 0
    assert labels.filter(~pl.col("is_mule")).filter(pl.col("layer_index") != -1).height == 0

    # Ring membership in labels matches the ring records exactly.
    for ring in dataset.rings:
        members = labels.filter(pl.col("ring_id") == ring.ring_id)
        assert members.height == len(ring.account_ids)
        assert members["is_mule"].all()

    # Mule prevalence stays realistic -- a dataset that is 30% mule would make
    # every downstream metric meaningless.
    prevalence = mules.height / labels.height
    assert 0.001 < prevalence < 0.05, f"mule prevalence {prevalence:.3%} is unrealistic"


def test_every_ring_has_a_cashout_path(dataset: GeneratedDataset) -> None:
    labels = dataset.labels
    for ring in dataset.rings:
        cashouts = labels.filter((pl.col("ring_id") == ring.ring_id) & pl.col("is_cashout_node"))
        assert cashouts.height > 0, f"ring {ring.ring_id} has no cash-out node"


def test_rings_share_infrastructure(dataset: GeneratedDataset) -> None:
    """The shared-infrastructure tell is the signal that beats per-account rules.

    If this does not hold, the graph model has nothing to learn that LightGBM
    on node features could not already see.
    """
    accounts = dataset.accounts.join(dataset.labels, on="account_id", how="inner")

    for ring in dataset.rings:
        members = accounts.filter(pl.col("ring_id") == ring.ring_id)
        n_devices = members["device_fingerprint"].n_unique()
        # Devices are shared in clusters, so distinct devices must be well
        # below the member count.
        assert n_devices < members.height, f"ring {ring.ring_id} shares no devices"

        # A meaningful bloc of the ring was opened inside one narrow window.
        # Deliberately *not* all of it -- see `ring_open_window_prob`. Testing
        # for the full membership would be testing that the dataset is easier
        # than it is.
        opened = sorted(members["open_date"].to_list())
        window = timedelta(days=settings.ring_open_window_days)
        best = max(
            sum(1 for other in opened if anchor <= other <= anchor + window)
            for anchor in opened
        )
        assert best >= 0.35 * members.height, (
            f"ring {ring.ring_id}: only {best}/{members.height} accounts were "
            "opened in a co-ordinated window"
        )


def test_ring_tells_are_not_universal(dataset: GeneratedDataset) -> None:
    """No single tell may identify every mule.

    This is the guard against the most damaging failure mode in the whole
    project: if every ring account carries every tell, the classes separate
    perfectly, both detectors score ~1.00 AUC-PR, and the benchmark measures
    nothing at all. The accounts carrying *no* individual tell are the ones the
    graph model exists to catch.
    """
    accounts = dataset.accounts.join(dataset.labels, on="account_id", how="inner")
    mules = accounts.filter(pl.col("is_mule"))
    assert mules.height > 0

    # Some mules were never dormant -- they were bought while already in use.
    never_dormant = mules.filter(
        pl.col("prior_activity_date") > pl.col("open_date")
    )
    assert never_dormant.height > 0, "every mule shows a dormancy break"

    # And some are on a device nobody else in their ring uses.
    device_counts = (
        mules.group_by(["ring_id", "device_fingerprint"]).len().rename({"len": "n"})
    )
    solo = device_counts.filter(pl.col("n") == 1)
    assert solo.height > 0, "every mule shares a device with a ring-mate"


def test_structuring_rings_sit_under_the_threshold(dataset: GeneratedDataset) -> None:
    """Structuring means deliberately staying below the reporting threshold."""
    threshold = settings.structuring_threshold_inr
    ring_ids = [r.ring_id for r in dataset.rings if r.typology == "structuring"]
    mule_ids = set(
        dataset.labels.filter(pl.col("ring_id").is_in(ring_ids))["account_id"].to_list()
    )

    laundered = dataset.transactions.filter(
        pl.col("src").is_in(mule_ids) & pl.col("dst").is_in(mule_ids)
    )
    assert laundered.height > 0
    assert laundered["amount"].max() < threshold


# --------------------------------------------------------------- hard negatives


def test_legit_high_velocity_accounts_exist_in_force(dataset: GeneratedDataset) -> None:
    """These are the hard negatives that break naive detectors.

    They must be numerous enough to actually hurt a bad model's precision.
    """
    hv = dataset.accounts.filter(pl.col("archetype") == "legit_high_velocity")
    expected = settings.n_accounts * settings.archetype_shares["legit_high_velocity"]
    assert hv.height == pytest.approx(expected, rel=0.02)

    # And they must not be secretly mules.
    hv_ids = set(hv["account_id"].to_list())
    flagged = dataset.labels.filter(pl.col("account_id").is_in(hv_ids) & pl.col("is_mule"))
    assert flagged.height == 0


# ------------------------------------------------------------------- scenarios


def test_all_six_scenarios_are_realised_in_the_data(dataset: GeneratedDataset) -> None:
    from app.simulator.scenarios import SCENARIOS

    assert len(SCENARIOS) == 6

    known_accounts = set(dataset.accounts["account_id"].to_list())
    ring_ids = {r.ring_id for r in dataset.rings}

    for scenario in SCENARIOS:
        assert scenario.victim_account in known_accounts
        assert scenario.ring_id in ring_ids

        # The victim's outbound transfer of the stolen amount must be present.
        outbound = dataset.transactions.filter(
            (pl.col("src") == scenario.victim_account)
            & (pl.col("timestamp") == scenario.incident_time)
        )
        assert outbound.height == 1, f"{scenario.scenario_id}: victim debit missing"
        assert outbound["amount"].item() == pytest.approx(scenario.amount_inr)


# --------------------------------------------------------------- reproducibility


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_same_seed_produces_byte_identical_files(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """A demo that changes between rehearsal and stage is a lost hackathon."""
    a = generate_dataset(out_dir=tmp_path_factory.mktemp("rep_a"))
    b = generate_dataset(out_dir=tmp_path_factory.mktemp("rep_b"))

    for name in ("accounts.parquet", "transactions.parquet", "labels.parquet"):
        assert _digest(a.out_dir / name) == _digest(b.out_dir / name), f"{name} differs"


def test_different_seed_produces_different_data(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Guards against the seed being ignored entirely, which would make the
    reproducibility test above vacuous."""
    a = generate_dataset(out_dir=tmp_path_factory.mktemp("seed_a"), seed=1)
    b = generate_dataset(out_dir=tmp_path_factory.mktemp("seed_b"), seed=2)
    assert _digest(a.out_dir / "transactions.parquet") != _digest(
        b.out_dir / "transactions.parquet"
    )