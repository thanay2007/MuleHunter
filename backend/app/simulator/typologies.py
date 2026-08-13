"""Mule ring archetypes and the laundering episodes they run.

Four typologies, three rings each. The structural differences between them are
the point: a detector tuned to fan-out width misses chain-and-burst entirely,
and a detector tuned to large transfers misses structuring by construction.

Ring accounts are *real accounts belonging to real people* -- rented or sold,
not fabricated. So they are drawn from the existing population (skewed toward
the low-income archetypes syndicates actually recruit from) and then have their
account-opening, device and dormancy attributes rewritten to the ring pattern.

The shared-infrastructure tells (device clusters, IP clusters, narrow opening
windows, long dormancy) are what let a graph model see one organisation where a
rule engine sees N unrelated grey accounts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import polars as pl

from app.config import settings
from app.simulator.population import to_epoch
from app.simulator.scenarios import (
    RESERVED_VICTIM_SLOTS,
    RING_TYPOLOGY_ORDER,
    RINGS_PER_TYPOLOGY,
    SCENARIOS,
    Scenario,
    ring_id_for,
)

# Archetypes syndicates recruit mules from. Deliberately excludes
# `legit_high_velocity`, which must stay clean so it can act as a hard negative.
RECRUIT_POOL: tuple[str, ...] = ("student", "homemaker", "salaried")
RECRUIT_WEIGHTS: tuple[float, ...] = (0.45, 0.35, 0.20)


@dataclass
class Episode:
    """One laundering run through a ring."""

    episode_id: str
    ring_id: str
    victim_account: str
    amount_inr: float
    start_time: datetime
    scenario_id: str | None = None


@dataclass
class Ring:
    """A mule ring: its members, its shape, and what it did."""

    ring_id: str
    typology: str
    account_ids: list[str]
    member_indices: list[int]
    layers: list[list[int]]  # local indices, layer 0 is the collector
    children: dict[int, list[int]]
    cashout_local: list[int]
    exit_kind: str
    episodes: list[Episode] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.account_ids)

    def layer_of(self, local: int) -> int:
        for depth, layer in enumerate(self.layers):
            if local in layer:
                return depth
        return -1


# ---------------------------------------------------------------------------
# ring shape
# ---------------------------------------------------------------------------


def _layer_widths(rng: np.random.Generator, typology: str, budget: int) -> list[int]:
    """Node count per layer, respecting the ring's total size budget.

    Unbounded branching would explode past any realistic ring size, so growth
    is allocated across the depth rather than compounded freely.
    """
    if typology == "fanout":
        depth = int(rng.integers(*settings.fanout_layers, endpoint=True))
        fan_lo, fan_hi = settings.fanout_splits
    elif typology == "chain_burst":
        depth = settings.chain_narrow_hops + 1
        fan_lo, fan_hi = settings.chain_narrow_fanout
    elif typology == "structuring":
        depth = 3
        fan_lo, fan_hi = 6, 12
    else:  # crypto_exit
        depth = int(rng.integers(*settings.crypto_hops, endpoint=True)) + 1
        fan_lo, fan_hi = 3, 6

    widths = [1]
    remaining = budget - 1

    for layer in range(1, depth):
        layers_left = depth - layer
        headroom = remaining - (layers_left - 1)  # keep >=1 for each later layer
        if headroom < 1:
            break

        if typology == "chain_burst" and layer == depth - 1:
            # The burst: narrow chain suddenly goes wide at the penultimate hop.
            target = int(rng.integers(*settings.chain_burst_splits, endpoint=True))
        else:
            target = widths[-1] * int(rng.integers(fan_lo, fan_hi, endpoint=True))

        width = max(1, min(target, headroom))
        widths.append(width)
        remaining -= width

    return widths


def _assign_children(
    rng: np.random.Generator, widths: list[int]
) -> tuple[list[list[int]], dict[int, list[int]]]:
    """Turn layer widths into an explicit tree."""
    layers: list[list[int]] = []
    cursor = 0
    for width in widths:
        layers.append(list(range(cursor, cursor + width)))
        cursor += width

    children: dict[int, list[int]] = {node: [] for layer in layers for node in layer}
    for depth in range(len(layers) - 1):
        parents = layers[depth]
        for position, child in enumerate(layers[depth + 1]):
            # Round-robin keeps parents balanced; the shuffle stops the
            # structure from being perfectly regular, which would be a tell.
            children[parents[position % len(parents)]].append(child)

    for parent, kids in children.items():
        if kids:
            rng.shuffle(kids)

    return layers, children


# ---------------------------------------------------------------------------
# ring construction
# ---------------------------------------------------------------------------


def inject_rings(
    rng: np.random.Generator, accounts: pl.DataFrame
) -> tuple[pl.DataFrame, list[Ring], np.ndarray]:
    """Select mule accounts, rewrite their attributes, and return the rings.

    Returns the updated account table, the rings, and a boolean mask of
    non-mule (`active`) accounts for background traffic generation.
    """
    n = accounts.height
    archetypes = accounts["archetype"].to_numpy()
    account_ids = accounts["account_id"].to_list()

    eligible = np.array(
        [
            i
            for i in range(RESERVED_VICTIM_SLOTS, n)
            if archetypes[i] in RECRUIT_POOL
        ]
    )
    weights = np.array(
        [RECRUIT_WEIGHTS[RECRUIT_POOL.index(archetypes[i])] for i in eligible]
    )
    weights = weights / weights.sum()

    sizes = [
        int(rng.integers(*settings.ring_size_range, endpoint=True))
        for _ in range(settings.n_rings)
    ]
    chosen = rng.choice(eligible, size=sum(sizes), replace=False, p=weights)

    open_dates = list(accounts["open_date"].to_list())
    devices = accounts["device_fingerprint"].to_list()
    ips = accounts["home_ip_prefix"].to_list()

    rings: list[Ring] = []
    cursor = 0

    for ring_index in range(settings.n_rings):
        typology = RING_TYPOLOGY_ORDER[ring_index // RINGS_PER_TYPOLOGY]
        rid = ring_id_for(typology, ring_index % RINGS_PER_TYPOLOGY)

        size = sizes[ring_index]
        members = [int(i) for i in chosen[cursor : cursor + size]]
        cursor += size

        widths = _layer_widths(rng, typology, size)
        layers, children = _assign_children(rng, widths)
        used = sum(widths)
        members = members[:used]

        _rewrite_ring_attributes(rng, rid, members, open_dates, devices, ips)

        rings.append(
            Ring(
                ring_id=rid,
                typology=typology,
                account_ids=[account_ids[i] for i in members],
                member_indices=members,
                layers=layers,
                children=children,
                # Any node with no onward transfer cashes out, not just the
                # final layer -- fan-out trees terminate at leaves scattered
                # across several depths, and every one of them is an exit.
                cashout_local=sorted(
                    local for local, kids in children.items() if not kids
                ),
                exit_kind="exchange" if typology == "crypto_exit" else "atm",
            )
        )

    updated = accounts.with_columns(
        pl.Series("open_date", open_dates),
        pl.Series("device_fingerprint", devices),
        pl.Series("home_ip_prefix", ips),
    )

    active = np.ones(n, dtype=bool)
    for ring in rings:
        active[ring.member_indices] = False

    return updated, rings, active


def _rewrite_ring_attributes(
    rng: np.random.Generator,
    ring_id: str,
    members: list[int],
    open_dates: list[date],
    devices: list[str],
    ips: list[str],
) -> None:
    """Stamp the shared-infrastructure tells onto a ring's accounts."""
    incident_day = date.fromisoformat(settings.sim_end_date)

    # Dormant for months before activation -- the classic rented-account tell.
    dormant_months = int(rng.integers(*settings.dormancy_months, endpoint=True))
    anchor = incident_day - timedelta(days=dormant_months * 30)

    # Accounts opened inside a narrow window, because one recruiter opened them.
    spread = settings.ring_open_window_days
    for local, index in enumerate(members):
        open_dates[index] = anchor - timedelta(days=int(rng.integers(0, spread + 1)))

        # Device and IP clusters: several accounts operated from one handset.
        cluster_size = int(rng.integers(*settings.device_cluster_size, endpoint=True))
        cluster = local // cluster_size
        devices[index] = f"DV-{ring_id}-{cluster:02d}"
        ips[index] = f"172.{abs(hash(ring_id)) % 200}.{cluster % 250}.0/24"


# ---------------------------------------------------------------------------
# laundering episodes
# ---------------------------------------------------------------------------


def _split_amounts(
    rng: np.random.Generator, amount: float, parts: int, cap: float | None
) -> list[float]:
    """Split an amount into near-equal parts, optionally under a hard cap."""
    if parts <= 0:
        return []

    # Structuring holds every transfer just below the reporting threshold, so
    # the number of transfers is driven by the cap rather than by fan-out.
    if cap is not None:
        lo, hi = settings.structuring_band_inr
        chunks: list[float] = []
        left = amount
        while left > 0.01:
            take = min(left, float(rng.uniform(lo, hi)))
            chunks.append(round(take, 2))
            left -= take
        return chunks

    weights = rng.dirichlet(np.full(parts, 12.0))  # tight -> near-equal splits
    values = [round(float(amount * w), 2) for w in weights]
    drift = round(amount - sum(values), 2)
    values[0] = round(values[0] + drift, 2)
    return [v for v in values if v > 0.01]


def simulate_episode(
    rng: np.random.Generator,
    ring: Ring,
    episode: Episode,
    account_ids: list[str],
    exit_nodes: pl.DataFrame,
    devices: list[str],
    ips: list[str],
    bridge: Ring | None = None,
) -> list[dict[str, object]]:
    """Push one victim's money through a ring and out of the banking system."""
    rows: list[dict[str, object]] = []
    cap = settings.structuring_threshold_inr if ring.typology == "structuring" else None

    def emit(
        src_id: str,
        dst_id: str,
        amount: float,
        when: datetime,
        channel: str,
        device: str,
        ip: str,
    ) -> None:
        rows.append(
            {
                "src": src_id,
                "dst": dst_id,
                "amount": round(amount, 2),
                "epoch": to_epoch(when),
                "channel": channel,
                "device_fingerprint": device,
                "ip_prefix": ip,
                "is_fraud": True,
                "ring_id": ring.ring_id,
            }
        )

    def member(local: int) -> int:
        return ring.member_indices[local]

    root = 0
    root_idx = member(root)

    # Victim -> collector account.
    emit(
        episode.victim_account,
        account_ids[root_idx],
        episode.amount_inr,
        episode.start_time,
        "IMPS" if episode.amount_inr > 100_000 else "UPI",
        devices[root_idx],
        ips[root_idx],
    )

    held: dict[int, float] = {root: episode.amount_inr}
    arrival: dict[int, datetime] = {root: episode.start_time}

    lo, hi = settings.fanout_delay_seconds

    for depth in range(len(ring.layers) - 1):
        for local in ring.layers[depth]:
            amount = held.pop(local, 0.0)
            kids = list(ring.children.get(local, []))
            if amount <= 0.01 or not kids:
                held[local] = amount
                continue

            # S5 launders through two rings: the collector bridges a slice of
            # the money into a second, structurally separate ring.
            bridge_share = 0.0
            if bridge is not None and depth == 0:
                bridge_share = amount * float(rng.uniform(0.35, 0.5))
                amount -= bridge_share

            chunks = _split_amounts(rng, amount, len(kids), cap)
            src_idx = member(local)

            for position, chunk in enumerate(chunks):
                child = kids[position % len(kids)]
                child_idx = member(child)
                when = arrival[local] + timedelta(
                    seconds=int(rng.integers(lo, hi, endpoint=True))
                )
                emit(
                    account_ids[src_idx],
                    account_ids[child_idx],
                    chunk,
                    when,
                    "UPI" if chunk < 100_000 else "IMPS",
                    devices[src_idx],
                    ips[src_idx],
                )
                held[child] = held.get(child, 0.0) + chunk
                arrival[child] = max(arrival.get(child, when), when)

            if bridge_share > 0.01:
                bridge_idx = bridge.member_indices[0]
                when = arrival[local] + timedelta(seconds=int(rng.integers(lo, hi)))
                rows.append(
                    {
                        "src": account_ids[src_idx],
                        "dst": account_ids[bridge_idx],
                        "amount": round(bridge_share, 2),
                        "epoch": to_epoch(when),
                        "channel": "IMPS",
                        "device_fingerprint": devices[src_idx],
                        "ip_prefix": ips[src_idx],
                        "is_fraud": True,
                        "ring_id": bridge.ring_id,
                    }
                )

    # --- cash out ---------------------------------------------------------
    exits = exit_nodes.filter(pl.col("exit_kind") == ring.exit_kind)["account_id"].to_list()
    per_txn_cap = (
        settings.atm_withdrawal_cap_inr
        if ring.exit_kind == "atm"
        else settings.exchange_deposit_cap_inr
    )
    channel = "ATM_WITHDRAWAL" if ring.exit_kind == "atm" else "IMPS"
    delay_lo, delay_hi = settings.cashout_delay_minutes

    for local, amount in held.items():
        if amount <= 1.0:
            continue
        src_idx = member(local)
        exit_id = exits[(src_idx + local) % len(exits)]
        when = episode.start_time + timedelta(
            minutes=int(rng.integers(delay_lo, delay_hi, endpoint=True))
        )

        n_txns = min(int(math.ceil(amount / per_txn_cap)), 12)
        for step in range(n_txns):
            slice_amount = amount / n_txns
            if cap is not None:
                slice_amount = min(slice_amount, settings.structuring_band_inr[1])
            emit(
                account_ids[src_idx],
                exit_id,
                slice_amount,
                when + timedelta(minutes=step * 3),
                channel,
                devices[src_idx],
                ips[src_idx],
            )

    return rows


def build_episodes(
    rng: np.random.Generator, rings: list[Ring], account_ids: list[str], active: np.ndarray
) -> None:
    """Attach episodes to each ring: the six scenarios plus randomised extras."""
    by_id = {ring.ring_id: ring for ring in rings}
    scenario_for: dict[str, Scenario] = {s.ring_id: s for s in SCENARIOS}

    legit = np.flatnonzero(active)
    end = date.fromisoformat(settings.sim_end_date)

    for ring in rings:
        counter = 0

        scenario = scenario_for.get(ring.ring_id)
        if scenario is not None:
            counter += 1
            ring.episodes.append(
                Episode(
                    episode_id=f"{ring.ring_id}-E{counter}",
                    ring_id=ring.ring_id,
                    victim_account=scenario.victim_account,
                    amount_inr=scenario.amount_inr,
                    start_time=scenario.incident_time,
                    scenario_id=scenario.scenario_id,
                )
            )

        extra = int(rng.integers(*settings.ring_episodes_range, endpoint=True))
        for _ in range(extra):
            counter += 1
            victim = account_ids[int(rng.choice(legit))]
            amount = float(np.clip(rng.lognormal(12.2, 0.9), 25_000, 6_000_000))
            day = end - timedelta(days=int(rng.integers(1, 12)))
            when = datetime(day.year, day.month, day.day) + timedelta(
                hours=int(rng.integers(8, 22)), minutes=int(rng.integers(0, 60))
            )
            ring.episodes.append(
                Episode(
                    episode_id=f"{ring.ring_id}-E{counter}",
                    ring_id=ring.ring_id,
                    victim_account=victim,
                    amount_inr=round(amount, 2),
                    start_time=when,
                )
            )

    # Keep the map alive for callers that resolve bridges by id.
    _ = by_id
