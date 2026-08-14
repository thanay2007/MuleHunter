"""Dataset orchestrator: population -> rings -> episodes -> parquet.

Run directly to write the dataset into `backend/data/`:

    python -m app.simulator.generator

Determinism is the hard requirement here. One master seed drives a
`SeedSequence` whose children are spawned in a fixed order, so the same seed
always produces byte-identical parquet files. Nothing reads the wall clock.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from app.config import settings
from app.simulator.population import (
    build_accounts,
    build_background_transactions,
    build_exit_nodes,
    window_bounds,
)
from app.simulator.typologies import Ring, build_episodes, inject_rings, simulate_episode

log = logging.getLogger(__name__)

TRANSACTION_COLUMNS: tuple[str, ...] = (
    "txn_id",
    "src",
    "dst",
    "amount",
    "timestamp",
    "channel",
    "device_fingerprint",
    "ip_prefix",
    "is_fraud",
    "ring_id",
)


@dataclass(frozen=True)
class GeneratedDataset:
    accounts: pl.DataFrame
    transactions: pl.DataFrame
    labels: pl.DataFrame
    episodes: pl.DataFrame
    rings: list[Ring]
    out_dir: Path
    elapsed_seconds: float


def generate_dataset(out_dir: Path | None = None, seed: int | None = None) -> GeneratedDataset:
    """Generate the full synthetic dataset and write it to `out_dir`."""
    started = time.perf_counter()
    out = out_dir if out_dir is not None else settings.data_dir
    out.mkdir(parents=True, exist_ok=True)

    root_seed = settings.master_seed if seed is None else seed
    # Spawn order is fixed, so each stage gets a stable independent stream.
    population_seed, ring_seed, traffic_seed, episode_seed = np.random.SeedSequence(
        root_seed
    ).spawn(4)

    accounts = build_accounts(np.random.default_rng(population_seed))
    exit_nodes = build_exit_nodes()

    accounts, rings, active = inject_rings(np.random.default_rng(ring_seed), accounts)

    # Episodes are scheduled before background traffic, because a mule account
    # is dormant until its ring first uses it and then behaves like an ordinary
    # account around the laundering runs. The traffic generator needs to know
    # that activation day to place -- and withhold -- ordinary activity.
    episode_rng = np.random.default_rng(episode_seed)
    account_ids = accounts["account_id"].to_list()
    build_episodes(episode_rng, rings, account_ids, active)

    background = build_background_transactions(
        np.random.default_rng(traffic_seed),
        accounts,
        exit_nodes,
        active,
        _activation_days(rings, accounts.height),
    )

    fraud_rows = _run_all_episodes(episode_rng, rings, accounts, exit_nodes)

    transactions = _finalise_transactions(background, fraud_rows)
    labels = _build_labels(accounts, rings)
    nodes = _combine_nodes(accounts, exit_nodes)
    episodes = _build_episodes_frame(rings)

    _write(out, nodes, transactions, labels, episodes, rings)

    elapsed = time.perf_counter() - started
    log.info(
        "generated %d transactions across %d accounts and %d rings in %.1fs",
        transactions.height,
        accounts.height,
        len(rings),
        elapsed,
    )

    return GeneratedDataset(
        accounts=nodes,
        transactions=transactions,
        labels=labels,
        episodes=episodes,
        rings=rings,
        out_dir=out,
        elapsed_seconds=elapsed,
    )


def _activation_days(rings: list[Ring], n_accounts: int) -> np.ndarray:
    """First day of the window on which each account may transact at all.

    Zero for everyone except mules, who are dormant until their ring's first
    laundering run. Returning this as a plain array keeps the traffic generator
    fully vectorised.
    """
    start, _ = window_bounds()
    live = np.zeros(n_accounts, dtype=np.int64)

    for ring in rings:
        if not ring.episodes:
            continue
        first = min(e.start_time.date() for e in ring.episodes)
        day = max(0, (first - start).days)
        for index in ring.member_indices:
            live[index] = day

    return live


def _run_all_episodes(
    rng: np.random.Generator,
    rings: list[Ring],
    accounts: pl.DataFrame,
    exit_nodes: pl.DataFrame,
) -> list[dict[str, object]]:
    by_id = {ring.ring_id: ring for ring in rings}
    account_ids = accounts["account_id"].to_list()
    devices = accounts["device_fingerprint"].to_list()
    ips = accounts["home_ip_prefix"].to_list()

    from app.simulator.scenarios import SCENARIOS

    bridge_for = {
        s.ring_id: by_id[s.secondary_ring_id]
        for s in SCENARIOS
        if s.secondary_ring_id is not None
    }

    legit_pool = _legit_payee_pool(accounts)

    rows: list[dict[str, object]] = []
    for ring in rings:
        for episode in ring.episodes:
            bridge = bridge_for.get(ring.ring_id) if episode.scenario_id else None
            rows.extend(
                simulate_episode(
                    rng,
                    ring,
                    episode,
                    account_ids,
                    exit_nodes,
                    devices,
                    ips,
                    bridge,
                    legit_pool,
                )
            )
    return rows


def _legit_payee_pool(accounts: pl.DataFrame) -> np.ndarray:
    """Real businesses a laundering hop might plausibly pay.

    Weighted to merchants and high-velocity traders, because that is who takes
    a large payment from a stranger without blinking. These accounts are wholly
    innocent and are labelled as such -- they exist to make the false-positive
    cost of freezing real.
    """
    from app.simulator.scenarios import RESERVED_VICTIM_SLOTS

    archetypes = accounts["archetype"].to_numpy()
    eligible = np.flatnonzero(
        (archetypes == "small_merchant") | (archetypes == "legit_high_velocity")
    )
    # Neither archetype is ever recruited as a mule (see RECRUIT_POOL), so
    # every account here is innocent by construction. Scenario victims are
    # excluded so a victim never receives their own laundered money.
    return eligible[eligible >= RESERVED_VICTIM_SLOTS].astype(np.int64)


def _finalise_transactions(
    background: pl.DataFrame, fraud_rows: list[dict[str, object]]
) -> pl.DataFrame:
    frames = [background]
    if fraud_rows:
        frames.append(pl.DataFrame(fraud_rows, schema=background.schema))

    combined = pl.concat(frames, how="vertical")

    # A total order over content, so txn_id assignment is reproducible.
    combined = combined.sort(["epoch", "src", "dst", "amount", "channel"])

    return combined.with_columns(
        pl.format("T{}", pl.int_range(pl.len()).cast(pl.Utf8).str.zfill(9)).alias("txn_id"),
        pl.from_epoch(pl.col("epoch"), time_unit="s").alias("timestamp"),
    ).select(TRANSACTION_COLUMNS)


def _build_labels(accounts: pl.DataFrame, rings: list[Ring]) -> pl.DataFrame:
    ids = accounts["account_id"].to_list()
    n = len(ids)

    is_mule = [False] * n
    ring_id = [""] * n
    layer_index = [-1] * n
    is_cashout = [False] * n
    typology = [""] * n

    for ring in rings:
        cashout = set(ring.cashout_local)
        for local, index in enumerate(ring.member_indices):
            is_mule[index] = True
            ring_id[index] = ring.ring_id
            layer_index[index] = ring.layer_of(local)
            is_cashout[index] = local in cashout
            typology[index] = ring.typology

    return pl.DataFrame(
        {
            "account_id": ids,
            "is_mule": is_mule,
            "ring_id": ring_id,
            "layer_index": layer_index,
            "is_cashout_node": is_cashout,
            "typology": typology,
        }
    )


def _build_episodes_frame(rings: list[Ring]) -> pl.DataFrame:
    """Every laundering run, as a first-class artifact.

    The evaluation harness needs a catalogue of incidents to benchmark over.
    Recovering one by inferring which fraud transfers look like episode roots
    would work today and break the first time the typologies change, so the
    generator writes down what it actually did.
    """
    rows = [
        {
            "episode_id": episode.episode_id,
            "ring_id": ring.ring_id,
            "typology": ring.typology,
            "victim_account": episode.victim_account,
            "amount_inr": episode.amount_inr,
            "start_time": episode.start_time,
            "scenario_id": episode.scenario_id or "",
        }
        for ring in rings
        for episode in ring.episodes
    ]
    return pl.DataFrame(rows).sort("start_time", "episode_id")


def _combine_nodes(accounts: pl.DataFrame, exit_nodes: pl.DataFrame) -> pl.DataFrame:
    retail = accounts.with_columns(pl.lit("").alias("exit_kind"))
    return pl.concat([retail, exit_nodes.select(retail.columns)], how="vertical")


def _write(
    out: Path,
    nodes: pl.DataFrame,
    transactions: pl.DataFrame,
    labels: pl.DataFrame,
    episodes: pl.DataFrame,
    rings: list[Ring],
) -> None:
    # zstd at a fixed level keeps the encoder deterministic run to run.
    nodes.write_parquet(out / "accounts.parquet", compression="zstd", compression_level=3)
    transactions.write_parquet(
        out / "transactions.parquet", compression="zstd", compression_level=3
    )
    labels.write_parquet(out / "labels.parquet", compression="zstd", compression_level=3)
    episodes.write_parquet(
        out / "episodes.parquet", compression="zstd", compression_level=3
    )
    (out / "summary.md").write_text(
        _summary(nodes, transactions, labels, rings), encoding="utf-8"
    )


def _summary(
    nodes: pl.DataFrame,
    transactions: pl.DataFrame,
    labels: pl.DataFrame,
    rings: list[Ring],
) -> str:
    start, end = window_bounds()
    retail = nodes.filter(pl.col("archetype") != "exit_point")
    mules = labels.filter(pl.col("is_mule"))
    fraud = transactions.filter(pl.col("is_fraud"))

    lines: list[str] = [
        "# Generated dataset summary",
        "",
        "All data is synthetic. No real bank data, no real PII, no real account numbers.",
        f"Generated from master seed `{settings.master_seed}`; regenerating with the same",
        "seed reproduces these files byte for byte.",
        "",
        "## Scale",
        "",
        f"- Window: {start} to {end} ({settings.sim_days} days)",
        f"- Retail accounts: {retail.height:,}",
        f"- Exit nodes (ATM / exchange / cross-border): {nodes.height - retail.height}",
        f"- Transactions: {transactions.height:,}",
        f"- Fraudulent transactions: {fraud.height:,} "
        f"({fraud.height / transactions.height:.2%})",
        f"- Mule accounts: {mules.height:,} ({mules.height / retail.height:.2%} prevalence)",
        "",
        "## Archetype mix",
        "",
        "| Archetype | Accounts | Share |",
        "|---|---:|---:|",
    ]

    mix = retail.group_by("archetype").len().sort("len", descending=True)
    for row in mix.iter_rows(named=True):
        lines.append(
            f"| {row['archetype']} | {row['len']:,} | {row['len'] / retail.height:.1%} |"
        )

    lines += [
        "",
        "## Channel mix",
        "",
        "| Channel | Transactions | Share |",
        "|---|---:|---:|",
    ]
    channels = transactions.group_by("channel").len().sort("len", descending=True)
    for row in channels.iter_rows(named=True):
        lines.append(
            f"| {row['channel']} | {row['len']:,} | "
            f"{row['len'] / transactions.height:.1%} |"
        )

    lines += [
        "",
        "## Injected rings",
        "",
        "| Ring | Typology | Accounts | Layers | Cash-out nodes | Episodes |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for ring in rings:
        lines.append(
            f"| {ring.ring_id} | {ring.typology} | {ring.size} | "
            f"{len(ring.layers)} | {len(ring.cashout_local)} | {len(ring.episodes)} |"
        )

    lines += [
        "",
        "## Hourly activity (diurnal curve)",
        "",
        "Transaction count by hour of day, IST. Peaks near 11:00 and 20:00.",
        "",
        "```",
    ]
    hourly = (
        transactions.with_columns(pl.col("timestamp").dt.hour().alias("hour"))
        .group_by("hour")
        .len()
        .sort("hour")
    )
    peak = max(hourly["len"].to_list())
    for row in hourly.iter_rows(named=True):
        bar = "#" * int(40 * row["len"] / peak)
        lines.append(f"{row['hour']:02d}  {bar:<40} {row['len']:,}")
    lines += ["```", ""]

    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level="INFO", format="%(message)s")
    dataset = generate_dataset()
    print(f"\nWrote {dataset.transactions.height:,} transactions to {dataset.out_dir}")
    print(f"Elapsed: {dataset.elapsed_seconds:.1f}s")


if __name__ == "__main__":
    main()
