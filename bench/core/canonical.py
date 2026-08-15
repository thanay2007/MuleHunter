"""The canonical case: one fraud incident, in a form every system can be shown.

There is exactly one definition of a case in this project and it lives here. The
benchmark runs on it, the Arena replays it, and `tools/export_case.py` is a
serializer rather than a second pipeline. Two definitions of "case" would mean
the number on the scorecard and the number in the report could drift apart
without anybody noticing, which is the failure mode this module exists to
prevent.

A canonical case carries four separable things:

  * **the skeleton** -- who is in the case, where the stolen money went, when,
    and where it left the banking system.
  * **the raw event log** -- every transaction touching any account in the pool,
    including ordinary traffic and including history from before the incident.
    This is what `build_observation` truncates; it is deliberately larger than
    the skeleton, because a detector is entitled to an account's normal life.
  * **the ground truth** -- kept in its own block, never merged into the
    accounts, so that handing a system an Observation cannot leak it.
  * **the layout** -- settled here, once, so the picture is identical on every
    machine and every reload.

Nothing in this module scores anything.
"""

from __future__ import annotations

import json
import logging
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
REPO = BENCH.parent
BACKEND = REPO / "backend"
for path in (str(BACKEND),):
    if path not in sys.path:
        sys.path.insert(0, path)

import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

from app.config import settings  # noqa: E402
from app.graphstore.build import load_dataset  # noqa: E402
from app.graphstore.features import FEATURE_NAMES, build_features  # noqa: E402
from app.graphstore.incidents import Incident, episodes_for  # noqa: E402
from app.graphstore.trace import (  # noqa: E402
    candidate_accounts,
    to_epoch,
    trace_taint,
    transaction_index,
)

log = logging.getLogger("bench.canonical")

CANONICAL_VERSION = "1.0"

#: The money's own path. Rings run to 180 accounts; an episode that lights up
#: 130 of them cannot be read on a projector and, worse, leaves no room for the
#: ordinary accounts that make the false-positive question real. Episodes wider
#: than this are skipped rather than trimmed -- trimming would break the flow
#: the whole picture is about.
MAX_CORE = 70
MIN_CORE = 8
#: Total accounts drawn. Sits under the Arena's 200-node performance target.
MAX_DRAWN = 190
#: How far back ordinary counterparties are gathered from.
CONTEXT_LOOKBACK_DAYS = 7
#: How much history each system may see. A month is what the feature code in
#: `app.graphstore.features` was written against, and it is what a bank has.
HISTORY_DAYS = 30

#: The pool every system scores: accounts the stolen money touched, plus
#: everything within two hops along edges observed before the complaint. Mostly
#: ordinary accounts, and deliberately not pre-filtered.
SCORING_HOPS = 2
SCORING_POOL_LIMIT = 900

TYPOLOGY_TO_SCENARIO = {
    "fanout": "layering",
    "structuring": "smurfing",
    "chain_burst": "rapid_cashout",
    "crypto_exit": "cross_bank_mixing",
}


# ---------------------------------------------------------------------------
# determinism helpers -- shared with the Arena so a draw made here and a draw
# made there agree
# ---------------------------------------------------------------------------


def mulberry32(seed: int):
    state = seed & 0xFFFFFFFF

    def rand() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = (t ^ (t >> 15)) * (t | 1) & 0xFFFFFFFF
        t ^= (t + ((t ^ (t >> 7)) * (t | 61) & 0xFFFFFFFF)) & 0xFFFFFFFF
        t &= 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return rand


def seed_from(text: str) -> int:
    """Stable 32-bit seed from a string. Never `hash()` -- Python salts that."""
    h = 2166136261
    for ch in text:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def display_id(account_id: str, bank: str) -> str:
    return f"{bank} ****{account_id[-4:]}"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe(value) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


# ---------------------------------------------------------------------------
# the skeleton
# ---------------------------------------------------------------------------


@dataclass
class Skeleton:
    incident: Incident
    t0: datetime
    complaint: datetime
    horizon: datetime
    core: list[str]
    pool: list[str]
    drawn: list[str]
    layer: dict[str, int]
    transfers: list[dict]
    context_edges: list[dict]
    cashouts: list[dict]
    truth: dict[str, bool]
    meta: dict[str, dict]
    attached_to: dict[str, str] = field(default_factory=dict)
    context_rank: dict[str, int] = field(default_factory=dict)


def build_skeleton(
    incident: Incident, dataset, index, max_core: int | None = MAX_CORE
) -> Skeleton | None:
    """Trace the money and assemble the pool every system will be asked about."""
    t0 = incident.incident_time
    horizon = t0 + timedelta(hours=settings.incident_horizon_hours)
    complaint = incident.complaint_time

    state = trace_taint(incident.victim_account, incident.amount_inr, t0, horizon, index)
    core = sorted(a for a in state.through if a not in index.exits)
    if len(core) < MIN_CORE or (max_core is not None and len(core) > max_core):
        return None

    children: dict[str, list[str]] = defaultdict(list)
    for flow in sorted(state.flows, key=lambda f: f.epoch):
        children[flow.src].append(flow.dst)
    layer = {incident.victim_account: 0}
    frontier = [incident.victim_account]
    while frontier:
        nxt: list[str] = []
        for node in frontier:
            for child in children.get(node, ()):
                if child not in layer:
                    layer[child] = layer[node] + 1
                    nxt.append(child)
        frontier = nxt

    pool = sorted(
        set(core)
        | set(
            candidate_accounts(
                state, hops=SCORING_HOPS, index=index, limit=SCORING_POOL_LIMIT
            )
        )
    )

    core_set = set(core)
    window = dataset.transactions.filter(
        (pl.col("timestamp") >= t0 - timedelta(days=CONTEXT_LOOKBACK_DAYS))
        & (pl.col("timestamp") <= horizon)
        & (pl.col("src").is_in(core_set) | pl.col("dst").is_in(core_set))
    ).select("src", "dst")

    context_score: dict[str, int] = defaultdict(int)
    attached_to: dict[str, str] = {}
    for src, dst in window.iter_rows():
        for near, far in ((src, dst), (dst, src)):
            if near in core_set and far not in core_set and far not in index.exits:
                context_score[far] += 1
                attached_to.setdefault(far, near)
    context_rank = {
        account: n
        for n, (account, _) in enumerate(
            sorted(context_score.items(), key=lambda kv: (-kv[1], kv[0]))
        )
    }

    transfers: list[dict] = []
    cashouts: list[dict] = []
    for n, flow in enumerate(sorted(state.flows, key=lambda f: (f.epoch, f.src, f.dst))):
        offset = max(0, flow.epoch - to_epoch(t0))
        if flow.dst in index.exits:
            kind = index.exit_kind.get(flow.dst, "atm")
            cashouts.append(
                {
                    "account_id": flow.src,
                    "amount_inr": round(flow.tainted, 2),
                    "t_offset_sec": offset,
                    "type": {
                        "atm": "atm",
                        "exchange": "crypto",
                        "crossborder": "forex",
                    }.get(kind, "merchant"),
                }
            )
            continue
        if flow.src not in core_set or flow.dst not in core_set:
            continue
        transfers.append(
            {
                "id": f"T{n:04d}",
                "from": flow.src,
                "to": flow.dst,
                "amount_inr": round(flow.tainted, 2),
                "gross_inr": round(flow.amount, 2),
                "t_offset_sec": offset,
                "channel": flow.channel,
                "status": "settled",
            }
        )
    cashouts = [c for c in cashouts if c["account_id"] in core_set]

    labels = dict(dataset.labels.select("account_id", "is_mule").iter_rows())
    meta = {
        row["account_id"]: row
        for row in dataset.accounts.filter(
            pl.col("account_id").is_in(set(pool))
        ).iter_rows(named=True)
    }
    pool = [a for a in pool if a in meta]
    core = [a for a in core if a in meta]

    return Skeleton(
        incident=incident,
        t0=t0,
        complaint=complaint,
        horizon=horizon,
        core=core,
        pool=pool,
        drawn=[],
        layer={a: int(v) for a, v in layer.items()},
        transfers=transfers,
        context_edges=[],
        cashouts=cashouts,
        truth={a: bool(labels.get(a, False)) for a in pool},
        meta=meta,
        attached_to=attached_to,
        context_rank=context_rank,
    )


def choose_drawn(skeleton: Skeleton, must_show: set[str], dataset) -> None:
    """Decide what gets drawn, then fill in layers and the ordinary edges.

    Three tiers: the money's path, every account any system flagged, then as much
    surrounding ordinary traffic as fits. The middle tier is the one that
    matters -- an account a system froze by mistake has to be on screen, or the
    false-positive column is a number with nothing behind it.
    """
    core_set = set(skeleton.core)
    flagged = sorted(a for a in must_show if a in skeleton.meta and a not in core_set)
    room = max(0, MAX_DRAWN - len(core_set) - len(flagged))
    context = sorted(
        (a for a in skeleton.pool if a not in core_set and a not in set(flagged)),
        key=lambda a: (skeleton.context_rank.get(a, 10**6), a),
    )[:room]

    drawn = sorted(core_set | set(flagged) | set(context))
    for account in drawn:
        if account in skeleton.layer:
            continue
        anchor = skeleton.attached_to.get(account)
        skeleton.layer[account] = min(skeleton.layer.get(anchor, 1) + 1, 9)
    skeleton.drawn = drawn

    in_scope = set(drawn)
    skeleton.transfers = [
        t for t in skeleton.transfers if t["from"] in in_scope and t["to"] in in_scope
    ]
    skeleton.cashouts = [
        c for c in skeleton.cashouts if c["account_id"] in in_scope
    ]

    tainted_pairs = {(t["from"], t["to"]) for t in skeleton.transfers}
    edges: list[dict] = []
    ordinary = (
        dataset.transactions.filter(
            (pl.col("timestamp") >= skeleton.t0 - timedelta(days=CONTEXT_LOOKBACK_DAYS))
            & (pl.col("timestamp") <= skeleton.horizon)
            & pl.col("src").is_in(in_scope)
            & pl.col("dst").is_in(in_scope)
        )
        .group_by(["src", "dst"])
        .agg(
            pl.col("amount").sum().alias("gross"),
            pl.col("timestamp").min().alias("first"),
        )
        .sort(["src", "dst"])
    )
    for src, dst, gross, first in ordinary.iter_rows():
        if src == dst or (src, dst) in tainted_pairs:
            continue
        edges.append(
            {
                "from": src,
                "to": dst,
                "gross_inr": round(float(gross), 2),
                "t_offset_sec": max(0, int((first - skeleton.t0).total_seconds())),
            }
        )
    skeleton.context_edges = edges


# ---------------------------------------------------------------------------
# the raw event log -- what `build_observation` truncates
# ---------------------------------------------------------------------------


def raw_events(skeleton: Skeleton, dataset) -> list[dict]:
    """Every transaction touching any pooled account, with a signed offset.

    Offsets before the incident are negative and that is correct: a bank can see
    an account's last month. Truncation at simulated time `t` keeps everything
    with `t_offset_sec <= t`, which therefore keeps the history and drops only
    the future.
    """
    scope = set(skeleton.pool)
    start = skeleton.t0 - timedelta(days=HISTORY_DAYS)
    rows = (
        dataset.transactions.filter(
            (pl.col("timestamp") >= start)
            & (pl.col("timestamp") <= skeleton.horizon)
            & (pl.col("src").is_in(scope) | pl.col("dst").is_in(scope))
        )
        .select("src", "dst", "amount", "timestamp", "channel")
        .sort(["timestamp", "src", "dst"])
    )
    t0 = skeleton.t0
    return [
        {
            "from": src,
            "to": dst,
            "amount_inr": round(float(amount), 2),
            "t_offset_sec": int((when - t0).total_seconds()),
            "channel": channel,
        }
        for src, dst, amount, when, channel in rows.iter_rows()
    ]


def account_records(skeleton: Skeleton, accounts: list[str]) -> list[dict]:
    """Static attributes a bank already holds. No labels, ever."""
    t0_date = skeleton.t0.date()
    out: list[dict] = []
    for account in accounts:
        row = skeleton.meta[account]
        out.append(
            {
                "id": account,
                "display_id": display_id(account, str(row["bank_id"])),
                "bank": str(row["bank_id"]),
                "kyc_level": {
                    "full": "full",
                    "small": "min",
                    "video": "video",
                    "none": "none",
                }[str(row["kyc_tier"])],
                "opened_at": row["open_date"].isoformat(),
                "account_age_days": float((t0_date - row["open_date"]).days),
                "prior_activity_at": row["prior_activity_date"].isoformat(),
                "dormancy_days_before": float(
                    (t0_date - row["prior_activity_date"]).days
                ),
                "device_fingerprint": str(row["device_fingerprint"]),
                "ip_prefix": str(row["home_ip_prefix"]),
                "archetype": str(row["archetype"]),
                "district": str(row["district"]),
            }
        )
    return out


# ---------------------------------------------------------------------------
# balances, features, layout, classification
# ---------------------------------------------------------------------------


def own_balances(skeleton: Skeleton, dataset, accounts: list[str]) -> dict[str, float]:
    """The account holder's own money, before the stolen funds arrived.

    The simulator carries no balances, so this is derived: the account's net
    position over the simulation window, floored so no account is worth nothing
    and capped so one hub does not dominate the wrongly-frozen figure. It is a
    modelled quantity, and every artifact that shows it says so -- it prices the
    harm of freezing an innocent account, which is the last place to put a number
    in quietly.
    """
    scope = set(accounts)
    inflow = dict(
        dataset.transactions.filter(pl.col("dst").is_in(scope))
        .group_by("dst")
        .agg(pl.col("amount").sum())
        .iter_rows()
    )
    outflow = dict(
        dataset.transactions.filter(pl.col("src").is_in(scope))
        .group_by("src")
        .agg(pl.col("amount").sum())
        .iter_rows()
    )
    return {
        account: round(
            clamp(
                float(inflow.get(account, 0.0)) - float(outflow.get(account, 0.0)),
                500.0,
                2_000_000.0,
            ),
            2,
        )
        for account in accounts
    }


def arena_features(
    skeleton: Skeleton, accounts: list[str], matrix, dataset
) -> dict[str, dict]:
    """The twelve features the Arena's inspector shows.

    A projection of our detector's own feature vector into terms a judge can read
    without a glossary, plus two -- cross-bank hops and beneficiary age -- that
    are properties of the path rather than of the account. These are for display;
    no system is scored on them.
    """
    column = {name: i for i, name in enumerate(FEATURE_NAMES)}
    row_of = matrix.index
    values = matrix.values

    bank_of = {a: str(skeleton.meta[a]["bank_id"]) for a in accounts}
    parent: dict[str, str] = {}
    for transfer in sorted(skeleton.transfers, key=lambda t: t["t_offset_sec"]):
        parent.setdefault(transfer["to"], transfer["from"])
    crossings: dict[str, int] = {skeleton.incident.victim_account: 0}

    def hops(account: str, guard: int = 0) -> int:
        if account in crossings:
            return crossings[account]
        if guard > 32 or account not in parent:
            return 0
        up = parent[account]
        value = hops(up, guard + 1) + (
            1 if bank_of.get(up) != bank_of.get(account) else 0
        )
        crossings[account] = value
        return value

    first_edge: dict[tuple[str, str], int] = {}
    for src, dst, epoch in (
        dataset.transactions.filter(pl.col("dst").is_in(set(accounts)))
        .select("src", "dst", pl.col("timestamp").dt.epoch(time_unit="s").alias("e"))
        .iter_rows()
    ):
        key = (src, dst)
        if key not in first_edge or epoch < first_edge[key]:
            first_edge[key] = int(epoch)

    arrival: dict[str, dict] = {}
    for transfer in sorted(skeleton.transfers, key=lambda t: t["t_offset_sec"]):
        arrival.setdefault(transfer["to"], transfer)

    out: dict[str, dict] = {}
    for account in accounts:
        i = row_of[account]
        credit = arrival.get(account)
        if credit is None:
            beneficiary_age = 0.0
        else:
            first = first_edge.get((credit["from"], account))
            credit_epoch = to_epoch(skeleton.t0) + credit["t_offset_sec"]
            beneficiary_age = (
                0.0 if first is None else max(0.0, (credit_epoch - first) / 60.0)
            )
        tier = str(skeleton.meta[account]["kyc_tier"])
        out[account] = {
            "pass_through_ratio": round(
                clamp(safe(values[i, column["turnover_ratio"]]), 0.0, 1.0), 4
            ),
            "median_hold_seconds": round(
                safe(values[i, column["median_residence_minutes"]]) * 60.0, 1
            ),
            "dormancy_days_before": round(safe(values[i, column["dormancy_days"]]), 1),
            "inbound_fanin": int(safe(values[i, column["in_degree"]])),
            "outbound_fanout": int(safe(values[i, column["out_degree"]])),
            "device_shared_count": int(safe(values[i, column["device_cluster_size"]])),
            "ip_shared_count": int(safe(values[i, column["ip_cluster_size"]])),
            "structuring_score": round(
                clamp(safe(values[i, column["structuring_band_share"]]), 0.0, 1.0), 4
            ),
            "cross_bank_hops": int(hops(account)),
            "account_age_days": round(safe(values[i, column["account_age_days"]]), 1),
            "kyc_mismatch": tier in ("small", "none"),
            "beneficiary_added_minutes_before": round(min(beneficiary_age, 525600.0), 1),
        }
    return out


def layout(skeleton: Skeleton, case_id: str):
    """Layered radial in 3D, layered DAG in 2D, settled here once.

    The Arena never runs a layout of its own, so the same case is
    pixel-identical on every reload and on every machine.
    """
    rand = mulberry32(seed_from(case_id))
    accounts = skeleton.drawn
    by_layer: dict[int, list[str]] = defaultdict(list)
    for account in accounts:
        by_layer[skeleton.layer[account]].append(account)
    for group in by_layer.values():
        group.sort(key=lambda a: (str(skeleton.meta[a]["bank_id"]), a))

    ring_radius, layer_height = 14.0, 9.0
    max_width = max(len(v) for v in by_layer.values())
    pos3: dict[str, np.ndarray] = {}
    pos2: dict[str, np.ndarray] = {}

    for depth in sorted(by_layer):
        group = by_layer[depth]
        radius = ring_radius * max(depth, 0) ** 0.86
        for i, account in enumerate(group):
            if depth == 0 and len(group) == 1:
                pos3[account] = np.array([0.0, 0.0, 0.0])
            else:
                angle = 2 * math.pi * (i + 0.5) / len(group) + 0.35 * depth
                jitter = (rand() - 0.5) * 0.16
                pos3[account] = np.array(
                    [
                        math.cos(angle + jitter) * radius * (1 + (rand() - 0.5) * 0.08),
                        -depth * layer_height,
                        math.sin(angle + jitter) * radius * (1 + (rand() - 0.5) * 0.08),
                    ]
                )
            span = max(len(group), 1)
            pos2[account] = np.array(
                [
                    (i + 0.5) / span * max_width * 5.6 - max_width * 2.8,
                    -depth * layer_height * 1.15,
                ]
            )

    neighbours: dict[str, list[str]] = defaultdict(list)
    for edge in list(skeleton.transfers) + list(skeleton.context_edges):
        neighbours[edge["from"]].append(edge["to"])
        neighbours[edge["to"]].append(edge["from"])

    # Ten relaxation passes, each constrained to the layer's own ring or band.
    # Enough to unpick crossings; not enough to let a node drift out of its
    # layer, because the layer *is* the reading of the picture.
    for _ in range(10):
        for depth in sorted(by_layer):
            group = by_layer[depth]
            if depth == 0 or len(group) < 2:
                continue
            radius = ring_radius * depth**0.86
            for account in group:
                peers = [p for p in neighbours.get(account, ()) if p in pos3]
                if not peers:
                    continue
                target = np.mean([pos3[p] for p in peers], axis=0)
                point = pos3[account] + 0.25 * (target - pos3[account])
                flat = np.array([point[0], point[2]])
                norm = float(np.linalg.norm(flat)) or 1.0
                flat = flat / norm * radius
                pos3[account] = np.array([flat[0], -depth * layer_height, flat[1]])
                target2 = float(np.mean([pos2[p][0] for p in peers]))
                pos2[account][0] += 0.3 * (target2 - pos2[account][0])

    return (
        {a: [round(float(v), 3) for v in pos3[a]] for a in accounts},
        {a: [round(float(v), 3) for v in pos2[a]] for a in accounts},
    )


def classify(skeleton: Skeleton) -> tuple[str, str]:
    """Scenario type and difficulty, both derived from the case, never typed."""
    mules = [a for a in skeleton.drawn if skeleton.truth.get(a)]
    rings: dict[str, int] = defaultdict(int)
    for account in mules:
        ring = str(skeleton.meta[account].get("ring_id") or "")
        if ring:
            rings[ring] += 1

    scenario = TYPOLOGY_TO_SCENARIO.get(skeleton.incident.typology, "layering")
    if len(rings) >= 2 and sorted(rings.values())[-2] >= max(2, 0.2 * len(mules)):
        scenario = "mixed"
    elif mules:
        as_of = skeleton.complaint.date()
        dormant = sum(
            1
            for a in mules
            if (as_of - skeleton.meta[a]["prior_activity_date"]).days >= 90
        )
        if dormant / len(mules) >= 0.8:
            scenario = "dormant_reactivation"

    depth = max(skeleton.layer.values()) if skeleton.layer else 1
    escaped = sum(
        c["amount_inr"]
        for c in skeleton.cashouts
        if c["t_offset_sec"] <= (skeleton.complaint - skeleton.t0).total_seconds()
    )
    pressure = (
        skeleton.incident.complaint_delay_minutes / 60.0
        + depth / 4.0
        + 3.0 * escaped / max(skeleton.incident.amount_inr, 1.0)
    )
    return scenario, ("easy" if pressure < 1.2 else "medium" if pressure < 2.4 else "hard")


def title_for(incident: Incident, hops: int, banks: int) -> str:
    shape = {
        "fanout": "Fan-out layering",
        "structuring": "Sub-threshold structuring",
        "chain_burst": "Narrow chain into a burst",
        "crypto_exit": "Crypto exit",
    }.get(incident.typology, incident.typology.replace("_", " ").title())
    return f"{shape}, {hops} hops, {banks} banks"


# ---------------------------------------------------------------------------
# writing a canonical case to disk
# ---------------------------------------------------------------------------


def write_canonical(
    case_id: str, skeleton: Skeleton, dataset, index, out_dir: Path
) -> dict:
    """Serialize the parts of a case that no model has yet influenced."""
    matrix = build_features(
        skeleton.pool,
        skeleton.incident.victim_account,
        skeleton.complaint,
        dataset,
        index,
    )
    feats = arena_features(skeleton, skeleton.pool, matrix, dataset)
    events = raw_events(skeleton, dataset)

    payload = {
        "canonical_version": CANONICAL_VERSION,
        "case_id": case_id,
        "t0": skeleton.t0.isoformat(),
        "horizon_sec": int((skeleton.horizon - skeleton.t0).total_seconds()),
        "complaint_offset_sec": int(
            (skeleton.complaint - skeleton.t0).total_seconds()
        ),
        "provenance": {
            "episode_id": skeleton.incident.episode_id,
            "ring_id": skeleton.incident.ring_id,
            "typology": skeleton.incident.typology,
            "scenario_id": skeleton.incident.scenario_id,
            "generator_seed": settings.master_seed,
        },
        "victim": {
            "account_id": skeleton.incident.victim_account,
            "display_id": display_id(
                skeleton.incident.victim_account,
                str(skeleton.meta[skeleton.incident.victim_account]["bank_id"]),
            ),
            "amount_inr": round(float(skeleton.incident.amount_inr), 2),
            "channel": skeleton.transfers[0]["channel"] if skeleton.transfers else "IMPS",
        },
        "pool": skeleton.pool,
        "core": skeleton.core,
        "accounts": account_records(skeleton, skeleton.pool),
        "display_features": feats,
        "truth": {
            a: ("mule" if skeleton.truth.get(a) else "innocent") for a in skeleton.pool
        },
        "transfers": skeleton.transfers,
        "cashout_events": skeleton.cashouts,
        "events": events,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{case_id}.json").write_text(
        json.dumps(payload, default=str), encoding="utf-8"
    )
    return payload


def load_canonical(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "CANONICAL_VERSION",
    "Skeleton",
    "build_skeleton",
    "choose_drawn",
    "raw_events",
    "account_records",
    "own_balances",
    "arena_features",
    "layout",
    "classify",
    "title_for",
    "write_canonical",
    "load_canonical",
    "episodes_for",
    "load_dataset",
    "transaction_index",
    "settings",
    "Incident",
]
