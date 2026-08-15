"""Turn the MuleHunter pipeline's output into MuleHunter Arena case files.

    python tools/export_case.py                 # write data/cases/case_001..012.json
    python tools/export_case.py --count 3       # a quick subset
    python tools/export_case.py --case S1       # one named scenario

WHAT THIS IS FOR. The Arena is a replay engine and nothing else. It draws what
this script wrote and never computes a detection result of its own. That split
is deliberate: it removes every source of stage risk, and it means the numbers a
judge reads on screen are the numbers the models actually produced, not numbers
a visualisation talked itself into.

WHAT ACTUALLY RUNS HERE. Four detection systems score the same accounts at the
same moment on the same case:

  mulehunter        the trained LightGBM detector in backend/models, scored on
                    features computed as of the complaint time. Attributions are
                    real SHAP values out of the booster.

  argus_prism       ARGUS-PRISM's WarmthScore, reimplemented from the six signal
                    functions in its own repository, with its own published
                    weights, evaluated as of the complaint time instead of the
                    wall clock.

  mule_hunter_gnn   MULE_HUNTER's graph feature set -- PageRank, in/out ratio,
                    reciprocity, community fraud rate, ring membership,
                    second-hop fraud rate -- computed exactly as its
                    feature_engineering.py computes them. Its SAGE->GAT network
                    cannot be executed here (it needs torch_geometric and its own
                    training corpus), so the features are read by a logistic model
                    fitted on training-ring incidents. See METHOD_NOTES: this is
                    their features and our learner, and the case file says so.

  poc_isoforest     mule-account-detection-poc, run as written: the same seven
                    features, StandardScaler, IsolationForest(contamination=0.12,
                    random_state=42), and the same risk_score ranking formula.

FAIRNESS. All four are cut at the same operating point (§ OPERATING POINTS), all
four share the same freeze-dispatch model, and no system gets to see anything
the others do not. Nothing in this file special-cases the family "ours". If our
system loses on a case, the case file records that it lost.

GROUND TRUTH is written into the case file because the Arena has to score the
result at Act 4 -- but the Arena strips it out of the payload the renderer sees
and holds it in a closure until then.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402
from sklearn.ensemble import IsolationForest  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from app.config import settings  # noqa: E402
from app.detect.gbdt import load_detector  # noqa: E402
from app.graphstore.build import load_dataset  # noqa: E402
from app.graphstore.features import FEATURE_NAMES, build_features  # noqa: E402
from app.graphstore.incidents import Incident, episodes_for  # noqa: E402
from app.graphstore.trace import (  # noqa: E402
    candidate_accounts,
    to_epoch,
    trace_taint,
    transaction_index,
)

log = logging.getLogger("export_case")

EXPORTER_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"

#: Every model may flag this many accounts per case in the default mode. A
#: bank's investigation desk has a fixed daily capacity, so an equal alert
#: budget is the operationally honest way to compare systems -- and it is the
#: only comparison in which "flag everything" is not a winning strategy.
DEFAULT_BUDGET = 12

#: Case size. Small enough to read on a projector, large enough that the
#: false-positive problem is real. Taint-touched accounts always survive; the
#: one-hop context around them is trimmed to fit.
#:
#: The context matters more than it looks. Without it every account on screen is
#: downstream of stolen money, every model scores near-perfectly, and the
#: false-positive half of the scorecard measures nothing. The ratio here puts
#: roughly two ordinary accounts on screen for every account the money touched.
MAX_ACCOUNTS = 190
MIN_ACCOUNTS = 8
#: Upper bound on the money's own path. Rings run to 180 accounts and an episode
#: that lights up 130 of them cannot be read on a projector -- and, worse, would
#: leave no room on screen for the ordinary accounts that make the
#: false-positive question real. Episodes wider than this are skipped, not
#: trimmed: trimming would break the flow the whole picture is about.
MAX_CORE = 70
#: How far back to look for ordinary counterparties of the accounts in the case.
CONTEXT_LOOKBACK_DAYS = 7

#: The pool every model actually scores. This is the real candidate frontier the
#: backend solver plans against -- the accounts taint has touched plus
#: everything within two hops of them along edges observed before the complaint.
#: It is mostly ordinary accounts, which is the point: a model has to reject
#: them itself rather than be handed a pre-filtered shortlist. Only a slice of
#: this pool is drawn, but the scores, ranks and thresholds all come from the
#: whole of it.
SCORING_HOPS = 2
SCORING_POOL_LIMIT = 900

#: Freeze dispatch, from backend settings, applied identically to all four
#: systems. An instruction takes this long to reach the holding bank, and only
#: this many can be in flight at once -- so a model that ranks the right account
#: first gets its freeze in earlier than one that ranks it eighth.
DISPATCH_LATENCY_SEC = int(settings.freeze_issue_latency_minutes * 60)
DISPATCH_PARALLEL = settings.freeze_parallel_dispatch


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def mulberry32(seed: int):
    """The same PRNG the Arena uses, so Python and JS agree on any shared draw."""
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
    """Masked identifier, the way a freeze order circulating between banks reads."""
    return f"{bank} ****{account_id[-4:]}"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe(value: float) -> float:
    if value is None or not math.isfinite(float(value)):
        return 0.0
    return float(value)


# ---------------------------------------------------------------------------
# case selection
# ---------------------------------------------------------------------------

#: Our four generator typologies mapped onto the Arena's scenario vocabulary.
TYPOLOGY_TO_SCENARIO = {
    "fanout": "layering",
    "structuring": "smurfing",
    "chain_burst": "rapid_cashout",
    "crypto_exit": "cross_bank_mixing",
}


@dataclass(frozen=True)
class Selection:
    case_id: str
    incident: Incident


def select_incidents(count: int, only: str | None = None) -> list[Selection]:
    """Pick the cases to export: every typology, both sides of the holdout split.

    Selection is deterministic and deliberately *not* filtered by how well we
    do on it. A demo whose case list has been curated for wins dies the moment
    a judge asks to pick a different one.
    """
    pool = episodes_for()
    # Complaint delays past this leave no room inside the six-hour horizon for
    # a freeze to land, so the case would be a replay of a foregone conclusion.
    pool = [i for i in pool if i.complaint_delay_minutes <= 130]
    pool.sort(key=lambda i: (i.typology, i.ring_id, i.episode_id))

    if only:
        chosen = [i for i in pool if only in (i.scenario_id, i.episode_id, i.incident_id)]
        if not chosen:
            raise SystemExit(f"no episode matches {only!r}")
        return [Selection(case_id="case_001", incident=chosen[0])]

    held = set(settings.holdout_ring_ids)
    by_bucket: dict[tuple[str, bool], list[Incident]] = defaultdict(list)
    for incident in pool:
        by_bucket[(incident.typology, incident.ring_id in held)].append(incident)

    # Within a bucket, take the larger frauds first. Not because they are easier
    # -- they are not -- but because a case worth ₹8,000 makes the recovery
    # counter meaningless and the whole demo is a recovery counter.
    for group in by_bucket.values():
        group.sort(key=lambda i: (-i.amount_inr, i.episode_id))

    # Round-robin across (typology, holdout) buckets so twelve cases cover every
    # laundering shape on both sides of the split rather than twelve fan-outs.
    buckets = sorted(by_bucket)
    out: list[Incident] = []
    depth = 0
    while len(out) < count and depth < 64:
        for key in buckets:
            if len(out) >= count:
                break
            group = by_bucket[key]
            if depth < len(group):
                out.append(group[depth])
        depth += 1

    # Scenario S1 is the stage demo and runs on a held-out ring; if it is in the
    # pool at all it goes first, because it is the case the script is written to.
    out.sort(key=lambda i: (i.scenario_id != "S1", i.typology, i.episode_id))
    return [
        Selection(case_id=f"case_{n + 1:03d}", incident=incident)
        for n, incident in enumerate(out[:count])
    ]


# ---------------------------------------------------------------------------
# the case skeleton: who is in it, what moved, when
# ---------------------------------------------------------------------------


@dataclass
class CaseFrame:
    """Everything derived from the data before any model is asked anything."""

    incident: Incident
    t0: datetime
    complaint: datetime
    horizon: datetime
    #: The money's own path: every account the victim's funds actually touched.
    core: list[str]
    #: What the models score -- the real candidate frontier, mostly ordinary.
    pool: list[str]
    #: What gets drawn. Filled in once the models have spoken, so that every
    #: account any system flagged is on screen whether or not it deserved to be.
    accounts: list[str]
    layer: dict[str, int]
    transfers: list[dict]
    context_edges: list[dict]
    cashouts: list[dict]
    truth: dict[str, bool]
    meta: dict[str, dict]
    exit_kind: dict[str, str]
    attached_to: dict[str, str]
    context_rank: dict[str, int]


def build_frame(
    incident: Incident, dataset, index, max_core: int | None = MAX_CORE
) -> CaseFrame | None:
    """Trace the money, then assemble the pool every model will be asked about.

    `max_core=None` lifts the width limit. Fitting a baseline is not a case that
    has to be readable on a projector, so training frames keep every account the
    money touched.
    """
    t0 = incident.incident_time
    horizon = t0 + timedelta(hours=settings.incident_horizon_hours)
    complaint = incident.complaint_time

    state = trace_taint(incident.victim_account, incident.amount_inr, t0, horizon, index)
    core = sorted(a for a in state.through if a not in index.exits)
    if len(core) < MIN_ACCOUNTS or (max_core is not None and len(core) > max_core):
        return None

    # Hops from the victim along the path the money actually took.
    children: dict[str, list[str]] = defaultdict(list)
    for flow in sorted(state.flows, key=lambda f: f.epoch):
        children[flow.src].append(flow.dst)
    layer = {incident.victim_account: 0}
    frontier = [incident.victim_account]
    while frontier:
        nxt = []
        for node in frontier:
            for child in children.get(node, ()):
                if child not in layer:
                    layer[child] = layer[node] + 1
                    nxt.append(child)
        frontier = nxt

    # The candidate frontier: what a real investigation would have in front of
    # it. Overwhelmingly ordinary accounts, and deliberately not pre-filtered --
    # every system has to reject them on its own.
    pool = sorted(
        set(core)
        | set(
            candidate_accounts(
                state, hops=SCORING_HOPS, index=index, limit=SCORING_POOL_LIMIT
            )
        )
    )

    # Ordinary neighbours of the core, ranked by how tightly they sit against
    # it. This ordering decides who gets drawn once the flagged accounts have
    # taken their places.
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

    # Transfers: the traced money only. The six-hour window around one incident
    # routinely contains other victims' money moving through the same ring, and
    # drawing all of it produces a canvas of edges unrelated to the complaint.
    in_scope = core_set
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
                    "type": {"atm": "atm", "exchange": "crypto", "crossborder": "forex"}.get(
                        kind, "merchant"
                    ),
                }
            )
            continue
        if flow.src not in in_scope or flow.dst not in in_scope:
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

    # Keep the two lists disjoint so no rupee is counted as both forwarded and
    # withdrawn.
    cashouts = [c for c in cashouts if c["account_id"] in in_scope]

    labels = dict(dataset.labels.select("account_id", "is_mule").iter_rows())
    meta = {
        row["account_id"]: row
        for row in dataset.accounts.filter(
            pl.col("account_id").is_in(set(pool))
        ).iter_rows(named=True)
    }
    pool = [a for a in pool if a in meta]
    core = [a for a in core if a in meta]

    return CaseFrame(
        incident=incident,
        t0=t0,
        complaint=complaint,
        horizon=horizon,
        core=core,
        pool=pool,
        accounts=[],
        layer={a: int(v) for a, v in layer.items()},
        transfers=transfers,
        context_edges=[],
        cashouts=cashouts,
        truth={a: bool(labels.get(a, False)) for a in pool},
        meta=meta,
        exit_kind=dict(index.exit_kind),
        attached_to=attached_to,
        context_rank=context_rank,
    )


def choose_visible(frame: CaseFrame, must_show: set[str], dataset) -> None:
    """Decide what gets drawn, then fill in layers and the ordinary edges.

    Three tiers, in this order: the money's path, every account any system
    flagged, and then as much of the surrounding ordinary traffic as fits. The
    middle tier is the one that matters -- an account a model froze by mistake
    has to be on screen, or the false-positive column is a number with nothing
    behind it.
    """
    core_set = set(frame.core)
    flagged = sorted(a for a in must_show if a in frame.meta and a not in core_set)
    room = max(0, MAX_ACCOUNTS - len(core_set) - len(flagged))
    context = sorted(
        (a for a in frame.pool if a not in core_set and a not in set(flagged)),
        key=lambda a: (frame.context_rank.get(a, 10**6), a),
    )[:room]

    visible = sorted(core_set | set(flagged) | set(context))
    for account in visible:
        if account in frame.layer:
            continue
        anchor = frame.attached_to.get(account)
        frame.layer[account] = min(frame.layer.get(anchor, 1) + 1, 9)
    frame.accounts = visible

    in_scope = set(visible)
    frame.transfers = [
        t for t in frame.transfers if t["from"] in in_scope and t["to"] in in_scope
    ]
    frame.cashouts = [c for c in frame.cashouts if c["account_id"] in in_scope]

    # Ordinary traffic between accounts in the picture. None of this is the
    # victim's money; it is drawn as a dim hairline so the graph reads as a
    # neighbourhood rather than as a laundering diagram with orphans floating
    # beside it.
    tainted_pairs = {(t["from"], t["to"]) for t in frame.transfers}
    edges: list[dict] = []
    ordinary = (
        dataset.transactions.filter(
            (pl.col("timestamp") >= frame.t0 - timedelta(days=CONTEXT_LOOKBACK_DAYS))
            & (pl.col("timestamp") <= frame.horizon)
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
                "t_offset_sec": max(0, int((first - frame.t0).total_seconds())),
            }
        )
    frame.context_edges = edges


# ---------------------------------------------------------------------------
# the twelve Arena features
# ---------------------------------------------------------------------------


def arena_features(
    frame: CaseFrame, accounts: list[str], matrix, dataset, index
) -> dict[str, dict]:
    """The feature block the inspector shows, per account.

    These are a projection of the detector's own feature vector into terms a
    judge can read without a glossary, plus two -- cross-bank hops and
    beneficiary age -- computed here because they are properties of the path
    rather than of the account.
    """
    column = {name: i for i, name in enumerate(FEATURE_NAMES)}
    row_of = matrix.index
    values = matrix.values

    # How many bank boundaries the money crossed to reach each account.
    bank_of = {a: str(frame.meta[a]["bank_id"]) for a in accounts}
    parent: dict[str, str] = {}
    for transfer in sorted(frame.transfers, key=lambda t: t["t_offset_sec"]):
        parent.setdefault(transfer["to"], transfer["from"])
    crossings: dict[str, int] = {frame.incident.victim_account: 0}

    def hops(account: str, guard: int = 0) -> int:
        if account in crossings:
            return crossings[account]
        if guard > 32 or account not in parent:
            return 0
        up = parent[account]
        value = hops(up, guard + 1) + (1 if bank_of.get(up) != bank_of.get(account) else 0)
        crossings[account] = value
        return value

    # How long the sender had been paying this account before the stolen money
    # arrived. Zero means the beneficiary was added for this transfer.
    first_edge: dict[tuple[str, str], int] = {}
    pair_scan = dataset.transactions.filter(
        pl.col("dst").is_in(set(accounts))
    ).select(
        "src", "dst", pl.col("timestamp").dt.epoch(time_unit="s").alias("epoch")
    )
    for src, dst, epoch in pair_scan.iter_rows():
        key = (src, dst)
        if key not in first_edge or epoch < first_edge[key]:
            first_edge[key] = int(epoch)

    arrival: dict[str, dict] = {}
    for transfer in sorted(frame.transfers, key=lambda t: t["t_offset_sec"]):
        arrival.setdefault(transfer["to"], transfer)

    out: dict[str, dict] = {}
    for account in accounts:
        i = row_of[account]
        credit = arrival.get(account)
        if credit is None:
            beneficiary_age = 0.0
        else:
            key = (credit["from"], account)
            first = first_edge.get(key)
            credit_epoch = to_epoch(frame.t0) + credit["t_offset_sec"]
            beneficiary_age = 0.0 if first is None else max(0.0, (credit_epoch - first) / 60.0)

        tier = str(frame.meta[account]["kyc_tier"])
        out[account] = {
            "pass_through_ratio": round(clamp(safe(values[i, column["turnover_ratio"]]), 0.0, 1.0), 4),
            "median_hold_seconds": round(safe(values[i, column["median_residence_minutes"]]) * 60.0, 1),
            "dormancy_days_before": round(safe(values[i, column["dormancy_days"]]), 1),
            "inbound_fanin": int(safe(values[i, column["in_degree"]])),
            "outbound_fanout": int(safe(values[i, column["out_degree"]])),
            "device_shared_count": int(safe(values[i, column["device_cluster_size"]])),
            "ip_shared_count": int(safe(values[i, column["ip_cluster_size"]])),
            "structuring_score": round(clamp(safe(values[i, column["structuring_band_share"]]), 0.0, 1.0), 4),
            "cross_bank_hops": int(hops(account)),
            "account_age_days": round(safe(values[i, column["account_age_days"]]), 1),
            "kyc_mismatch": tier in ("small", "none"),
            "beneficiary_added_minutes_before": round(min(beneficiary_age, 525600.0), 1),
        }
    return out


# ---------------------------------------------------------------------------
# balances
# ---------------------------------------------------------------------------


def own_balances(frame: CaseFrame, dataset) -> dict[str, float]:
    """The account holder's own money, before the stolen funds arrived.

    The simulator does not carry balances, so this is derived: the account's net
    position over the simulation window, floored so no account is worth nothing
    and capped so one hub does not dominate the wrongly-frozen figure. It is a
    modelled quantity and the case file and README both say so -- it is what
    prices the harm of freezing an innocent account, and inventing a number
    quietly there would be exactly the wrong place to do it.
    """
    scope = set(frame.accounts)
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
    out: dict[str, float] = {}
    for account in frame.accounts:
        net = float(inflow.get(account, 0.0)) - float(outflow.get(account, 0.0))
        out[account] = round(clamp(net, 500.0, 2_000_000.0), 2)
    return out


# ---------------------------------------------------------------------------
# model 1 -- ours
# ---------------------------------------------------------------------------

#: Plain-English renderings of the detector's own features. The inspector reads
#: these; `structuring_band_share` is not a sentence a judge should have to
#: parse.
def humanise(feature: str, value: float, features: dict) -> str:
    v = safe(value)
    text = {
        "turnover_ratio": lambda: (
            f"Forwarded {min(v, 1.0):.0%} of every rupee it received"
            + (
                f", holding each credit for {features['median_hold_seconds']:.0f} seconds"
                if features["median_hold_seconds"] < 600
                else ""
            )
        ),
        "median_residence_minutes": lambda: (
            f"Money sat here for a median of {v * 60:.0f} seconds before moving on"
            if v < 10
            else f"Money sat here for a median of {v:.0f} minutes before moving on"
        ),
        "outflow_within_10min_share": lambda: f"{v:.0%} of its transfers went out within ten minutes of a credit",
        "dormancy_days": lambda: f"Dormant for {v:.0f} days, then active inside this incident",
        "device_cluster_size": lambda: f"Shares a device fingerprint with {max(0, int(v) - 1)} other accounts",
        "device_peers_in_incident": lambda: f"{int(v)} other accounts on the same handset are standing in the path of this same money",
        "ip_cluster_size": lambda: f"Shares an IP range with {max(0, int(v) - 1)} other accounts",
        "recipient_jaccard_max": lambda: f"Pays {v:.0%} of the same counterparties as another account in this case",
        "same_window_openings": lambda: f"{int(v)} of its graph neighbours opened accounts within the same three-week window",
        "structuring_band_share": lambda: f"{v:.0%} of its transfers were held just under the ₹50,000 reporting threshold",
        "max_fanout_10min": lambda: f"Paid {int(v)} different recipients inside a single ten-minute window",
        "fanout_ratio": lambda: f"Sends to {v:.1f} recipients for every account it receives from",
        "in_out_ratio_1h": lambda: f"Sent {v:.1f}x what it received in the last hour",
        "in_out_ratio_6h": lambda: f"Sent {v:.1f}x what it received over six hours",
        "in_out_ratio_24h": lambda: f"Sent {v:.1f}x what it received over a day",
        "hops_to_exit": lambda: (
            "Sits one hop from a cash-out point" if v <= 1 else f"Sits {v:.0f} hops from the nearest cash-out point"
        ),
        "exit_adjacent": lambda: "Pays a cash-out point directly",
        "exchange_flag": lambda: "Sends to a crypto exchange deposit account",
        "crossborder_flag": lambda: "Sends money cross-border",
        "atm_value_share": lambda: f"{v:.0%} of the value it sent left as cash at an ATM",
        "account_age_days": lambda: f"The account is {v:.0f} days old",
        "betweenness": lambda: "Sits on a bottleneck the money has to pass through",
        "pagerank": lambda: "Central to the flow in this incident",
        "amount_cv": lambda: (
            "Its outgoing amounts are near-identical, which is hard to produce by accident"
            if v < 0.35
            else f"Its outgoing amounts vary by a factor of {v:.1f}"
        ),
        "round_amount_share": lambda: f"{v:.0%} of its transfers were round numbers",
        "night_activity_share": lambda: f"{v:.0%} of its activity happened between 23:00 and 05:00",
        "kyc_small_flag": lambda: "Opened as a small (limited KYC) account",
        "kyc_video_flag": lambda: "Opened by video KYC, never in a branch",
        "reciprocity": lambda: (
            "Pays no one who pays it -- the flow is one-directional"
            if v < 0.05
            else f"{v:.0%} of its counterparties both pay it and are paid by it"
        ),
        "in_degree": lambda: f"Receives from {int(v)} different accounts",
        "out_degree": lambda: f"Sends to {int(v)} different accounts",
        "txn_count": lambda: f"{int(v)} transfers in the window",
        "burstiness": lambda: "Long silence, then a flurry of activity",
        "hops_from_victim": lambda: f"{v:.0f} hops from the victim",
        "log_max_credit": lambda: f"Largest single credit received: ₹{math.expm1(v):,.0f}",
        "log_total_out": lambda: f"Total value sent: ₹{math.expm1(v):,.0f}",
        "activity_span_hours": lambda: f"All of its activity fits in {v:.1f} hours",
    }.get(feature)
    return text() if text else f"{feature.replace('_', ' ')}: {v:,.2f}"


def score_ours(frame: CaseFrame, matrix, arena_feats: dict) -> tuple[dict[str, float], dict[str, list[dict]]]:
    detector = load_detector()
    if detector is None:
        raise SystemExit(
            "No trained detector in backend/models. Run: python -m app.detect.train"
        )
    scores = detector.score(matrix)
    contributions = detector.shap(matrix)

    out_scores: dict[str, float] = {}
    signals: dict[str, list[dict]] = {}
    for i, account in enumerate(matrix.account_ids):
        out_scores[account] = float(clamp(scores[i], 0.0, 1.0))
        row = contributions[i, : len(FEATURE_NAMES)]
        order = np.argsort(-np.abs(row))[:3]
        total = float(np.abs(row).sum()) or 1.0
        signals[account] = [
            {
                "feature": FEATURE_NAMES[j],
                "contribution": round(float(abs(row[j])) / total, 4),
                "direction": "up" if row[j] >= 0 else "down",
                "human_text": humanise(
                    FEATURE_NAMES[j], float(matrix.values[i, j]), arena_feats[account]
                ),
            }
            for j in order
        ]
    return out_scores, signals


# ---------------------------------------------------------------------------
# model 2 -- ARGUS-PRISM WarmthScore
# ---------------------------------------------------------------------------

#: ARGUS-PRISM's own weights, from
#: ARGUS-PRISM/backend/app/engines/warmthscore/signals.py. They sum to 100.
WARMTH_WEIGHTS = {
    "s1_velocity": 20.0,
    "s2_round_trip": 30.0,
    "s3_structuring": 14.0,
    "s4_dormant_device": 14.0,
    "s5_profile_mismatch": 12.0,
    "s6_sim_swap": 10.0,
}

#: Their segment throughput expectations, mapped onto our archetypes.
SEGMENT_OF_ARCHETYPE = {
    "salaried": "salary",
    "small_merchant": "business",
    "student": "student",
    "homemaker": "retail",
    "hnw": "business",
    "legit_high_velocity": "business",
    "exit_point": "business",
}
SEGMENT_EXPECTED = {
    "salary": 150_000.0,
    "retail": 80_000.0,
    "student": 30_000.0,
    "business": 1_500_000.0,
    "senior": 60_000.0,
}
STRUCTURING_THRESHOLD = 50_000.0


def score_argus_prism(
    frame: CaseFrame, accounts: list[str], dataset, arena_feats: dict
) -> tuple[dict[str, float], dict[str, list[dict]]]:
    """WarmthScore, their six signals and their weights, as of the complaint.

    The one adaptation: their signal functions call `datetime.now()`, which in a
    replay would measure the age of the dataset rather than the age of the
    incident. Every clock reference here is the complaint time instead. That is
    the change that makes the comparison meaningful; nothing else moves.
    """
    scope = set(accounts)
    until = frame.complaint
    window = dataset.transactions.filter(
        (pl.col("timestamp") <= until)
        & (pl.col("src").is_in(scope) | pl.col("dst").is_in(scope))
    ).select("src", "dst", "amount", "timestamp")

    recent_cut = until - timedelta(hours=48)
    inflow: dict[str, float] = defaultdict(float)
    outflow: dict[str, float] = defaultdict(float)
    throughput: dict[str, float] = defaultdict(float)
    recent_count: dict[str, int] = defaultdict(int)
    near_threshold: dict[str, int] = defaultdict(int)

    for src, dst, amount, when in window.iter_rows():
        amount = float(amount)
        fresh = when >= recent_cut
        near = 0.5 * STRUCTURING_THRESHOLD <= amount < STRUCTURING_THRESHOLD
        if src in scope:
            outflow[src] += amount
            throughput[src] += amount
            if fresh:
                recent_count[src] += 1
            if near:
                near_threshold[src] += 1
        if dst in scope:
            inflow[dst] += amount
            throughput[dst] += amount
            if fresh:
                recent_count[dst] += 1
            if near:
                near_threshold[dst] += 1

    scores: dict[str, float] = {}
    signals: dict[str, list[dict]] = {}
    as_of = until.date()

    for account in accounts:
        meta = frame.meta[account]
        feats = arena_feats[account]

        n_recent = recent_count[account]
        s1 = clamp((n_recent - 3) / 12.0, 0.0, 1.0)

        received = inflow[account]
        if received <= 0:
            s2 = 0.0
        else:
            ratio = min(1.0, outflow[account] / received)
            s2 = clamp((ratio - 0.5) / 0.5, 0.0, 1.0) if ratio > 0.5 else 0.0

        s3 = clamp((near_threshold[account] - 2) / 6.0, 0.0, 1.0)

        dormant_days = float((as_of - meta["prior_activity_date"]).days)
        shares_device = feats["device_shared_count"] > 1
        s4 = min(1.0, dormant_days / 180 + 0.3) if (shares_device and dormant_days > 90) else 0.0

        expected = SEGMENT_EXPECTED[SEGMENT_OF_ARCHETYPE.get(str(meta["archetype"]), "retail")]
        profile_ratio = throughput[account] / expected if expected else 0.0
        s5 = clamp((profile_ratio - 1.5) / 4.5, 0.0, 1.0)

        # ARGUS-PRISM's S6 reads SIM-swap velocity from a telco feed. Our
        # dataset has no telco feed, so this signal is zero for every account
        # in every case -- it is not evidence against them, it is a capability
        # they have and this benchmark cannot exercise. Recorded here so the
        # missing 10 points of their scale are visible rather than silent.
        s6 = 0.0

        raw = {
            "s1_velocity": s1,
            "s2_round_trip": s2,
            "s3_structuring": s3,
            "s4_dormant_device": s4,
            "s5_profile_mismatch": s5,
            "s6_sim_swap": s6,
        }
        total = sum(raw[k] * w for k, w in WARMTH_WEIGHTS.items()) / 100.0
        scores[account] = round(clamp(total, 0.0, 1.0), 6)

        weighted = sorted(
            ((k, raw[k] * WARMTH_WEIGHTS[k] / 100.0) for k in raw),
            key=lambda kv: -kv[1],
        )[:3]
        denominator = sum(v for _, v in weighted) or 1.0
        human = {
            "s1_velocity": f"{n_recent} transfers in the 48 hours before the complaint",
            "s2_round_trip": f"Sent {min(1.0, outflow[account] / max(received, 1.0)):.0%} of everything it received straight back out",
            "s3_structuring": f"{near_threshold[account]} transfers held between ₹25,000 and ₹50,000",
            "s4_dormant_device": f"Dormant {dormant_days:.0f} days and reactivated on a shared device",
            "s5_profile_mismatch": f"Moved {profile_ratio:.1f}x what its customer segment normally moves",
            "s6_sim_swap": "No SIM-swap feed available in this dataset",
        }
        signals[account] = [
            {
                "feature": name,
                "contribution": round(value / denominator, 4),
                "direction": "up",
                "human_text": human[name],
            }
            for name, value in weighted
        ]
    return scores, signals


# ---------------------------------------------------------------------------
# model 3 -- MULE_HUNTER graph features
# ---------------------------------------------------------------------------

MH_FEATURES = (
    "pagerank",
    "in_out_ratio",
    "reciprocity_score",
    "community_fraud_rate",
    "ring_membership",
    "second_hop_fraud_rate",
    "account_age_days",
    "tx_count",
    "fan_out_ratio",
)

MH_HUMAN = {
    "pagerank": "PageRank centrality in the transaction graph",
    "in_out_ratio": "Value received against value sent",
    "reciprocity_score": "Share of counterparties it both pays and is paid by",
    "community_fraud_rate": "Share of its detected community already known to be fraudulent",
    "ring_membership": "Number of short circular money flows it participates in",
    "second_hop_fraud_rate": "Share of its direct neighbours already known to be fraudulent",
    "account_age_days": "Age of the account",
    "tx_count": "Transfers in the window",
    "fan_out_ratio": "Recipients per sender",
}


def mule_hunter_features(
    accounts: list[str], dataset, until: datetime, known_mules: set[str], meta: dict
) -> np.ndarray:
    """Their feature_engineering.py, computed on the case graph.

    `community_fraud_rate` and `second_hop_fraud_rate` are guilt-by-association
    features: in their pipeline both are computed from the `is_fraud` column of
    the neighbours. At inference time on a live incident nobody has that column,
    so what a deployed version of their system would actually see is the set of
    accounts already *known* to be mules -- a watchlist from previously worked
    cases. That is what is passed in as `known_mules`, and it contains only
    accounts from training rings. On a held-out ring both features collapse
    towards zero, which is a real property of the method and one of the things
    this benchmark is here to show.
    """
    scope = set(accounts)
    edges = (
        dataset.transactions.filter(
            (pl.col("timestamp") <= until)
            & pl.col("src").is_in(scope)
            & pl.col("dst").is_in(scope)
        )
        .group_by(["src", "dst"])
        .agg(pl.col("amount").sum().alias("weight"), pl.len().alias("n"))
    )

    graph = nx.DiGraph()
    graph.add_nodes_from(accounts)
    for src, dst, weight, _n in edges.iter_rows():
        graph.add_edge(src, dst, weight=float(weight))

    pagerank = (
        nx.pagerank(graph, alpha=0.85, max_iter=200, weight="weight")
        if graph.number_of_edges()
        else {a: 0.0 for a in accounts}
    )

    # Communities by greedy modularity, exactly as they do it.
    try:
        communities = list(nx.community.greedy_modularity_communities(graph.to_undirected()))
    except Exception:  # noqa: BLE001 -- their code falls back the same way
        communities = list(nx.connected_components(graph.to_undirected()))
    community_rate: dict[str, float] = {}
    for group in communities:
        members = list(group)
        rate = sum(1 for m in members if m in known_mules) / max(len(members), 1)
        for member in members:
            community_rate[member] = rate

    # Bounded ring detection: their BFS-depth-limited search, same limits.
    ring_count: dict[str, int] = defaultdict(int)
    seen_rings: set[frozenset] = set()
    for start in accounts:
        stack = [(start, [start])]
        while stack and len(seen_rings) < 300:
            node, path = stack.pop()
            if len(path) > 6:
                continue
            for neighbour in graph.successors(node):
                if neighbour == start and len(path) >= 3:
                    key = frozenset(path)
                    if key not in seen_rings:
                        seen_rings.add(key)
                        for member in path:
                            ring_count[member] += 1
                elif neighbour not in path:
                    stack.append((neighbour, path + [neighbour]))

    counts = (
        dataset.transactions.filter(
            (pl.col("timestamp") <= until)
            & (pl.col("src").is_in(scope) | pl.col("dst").is_in(scope))
        )
        .select("src", "dst")
    )
    tx_count: dict[str, int] = defaultdict(int)
    for src, dst in counts.iter_rows():
        if src in scope:
            tx_count[src] += 1
        if dst in scope:
            tx_count[dst] += 1

    as_of = until.date()
    rows = np.zeros((len(accounts), len(MH_FEATURES)), dtype=np.float64)
    for i, account in enumerate(accounts):
        out_amount = sum(d.get("weight", 0.0) for _, _, d in graph.out_edges(account, data=True))
        in_amount = sum(d.get("weight", 0.0) for _, _, d in graph.in_edges(account, data=True))
        successors = set(graph.successors(account))
        predecessors = set(graph.predecessors(account))
        neighbours = list(successors | predecessors)
        second_hop = (
            sum(1 for n in neighbours if n in known_mules) / len(neighbours) if neighbours else 0.0
        )
        rows[i] = [
            pagerank.get(account, 0.0),
            in_amount / (out_amount + 1e-5),
            len(successors & predecessors) / (len(successors) + 1),
            community_rate.get(account, 0.0),
            float(ring_count[account]),
            second_hop,
            float((as_of - meta[account]["open_date"]).days),
            float(tx_count[account]),
            len(successors) / max(len(predecessors), 1),
        ]
    return np.nan_to_num(rows, nan=0.0, posinf=0.0, neginf=0.0)


def fit_mule_hunter(dataset, index, known_mules: set[str], training: list[Incident]):
    """Fit the learner that stands in for their SAGE->GAT network.

    Their architecture cannot be executed here: it needs torch_geometric and the
    corpus it was trained on, neither of which travels with this repository. So
    the substitution is stated rather than hidden -- their features, our
    learner, fitted on incidents from training rings only. A logistic model on
    nine graph features is weaker than a three-layer GNN, and where their
    approach wins in the results it wins on the features, which is the part of
    their system this benchmark can honestly measure.
    """
    matrices: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    labels = dict(dataset.labels.select("account_id", "is_mule").iter_rows())

    for incident in training:
        frame = build_frame(incident, dataset, index, max_core=None)
        if frame is None:
            continue
        rows = mule_hunter_features(
            frame.pool, dataset, frame.complaint, known_mules, frame.meta
        )
        matrices.append(rows)
        targets.append(
            np.array([1.0 if labels.get(a, False) else 0.0 for a in frame.pool])
        )
        if sum(m.shape[0] for m in matrices) > 4000:
            break

    if not matrices:
        raise SystemExit("could not assemble a training set for the MULE_HUNTER baseline")

    x = np.vstack(matrices)
    y = np.concatenate(targets)
    scaler = StandardScaler().fit(x)
    model = LogisticRegression(max_iter=2000, class_weight="balanced")
    model.fit(scaler.transform(x), y)
    log.info(
        "MULE_HUNTER baseline fitted on %d rows from %d training incidents (%.1f%% positive)",
        len(y),
        len(matrices),
        100.0 * y.mean(),
    )
    return scaler, model


def score_mule_hunter(
    frame: CaseFrame, accounts: list[str], dataset, fitted, known_mules: set[str]
) -> tuple[dict[str, float], dict[str, list[dict]]]:
    scaler, model = fitted
    rows = mule_hunter_features(
        accounts, dataset, frame.complaint, known_mules, frame.meta
    )
    scaled = scaler.transform(rows)
    probability = model.predict_proba(scaled)[:, 1]
    weights = model.coef_[0]

    scores: dict[str, float] = {}
    signals: dict[str, list[dict]] = {}
    for i, account in enumerate(accounts):
        scores[account] = float(clamp(probability[i], 0.0, 1.0))
        contribution = scaled[i] * weights
        order = np.argsort(-np.abs(contribution))[:3]
        total = float(np.abs(contribution).sum()) or 1.0
        signals[account] = [
            {
                "feature": MH_FEATURES[j],
                "contribution": round(float(abs(contribution[j])) / total, 4),
                "direction": "up" if contribution[j] >= 0 else "down",
                "human_text": f"{MH_HUMAN[MH_FEATURES[j]]}: {rows[i, j]:,.3f}",
            }
            for j in order
        ]
    return scores, signals


# ---------------------------------------------------------------------------
# model 4 -- mule-account-detection-poc
# ---------------------------------------------------------------------------

POC_FEATURES = (
    "account_age_days",
    "kyc_risk",
    "shared_device_count",
    "txn_count",
    "txn_sum",
    "txn_avg",
    "velocity_score",
)

#: Their kyc_risk column is an integer 1..4 with no stated mapping, so ours is
#: the obvious one: the weaker the verification, the higher the risk.
KYC_RISK = {"full": 1, "video": 2, "small": 3, "none": 4}


def fit_poc(dataset):
    """Their IsolationForest, fitted the way their train_model.py fits it.

    They fit on the whole account population rather than per case, so this does
    too -- on a deterministic 20,000-account slice, which is all their feature
    set needs and keeps the export inside a minute.
    """
    accounts = dataset.accounts.sort("account_id").head(20_000)
    scope = set(accounts["account_id"].to_list())
    aggregate = (
        dataset.transactions.filter(pl.col("src").is_in(scope))
        .group_by("src")
        .agg(
            pl.len().alias("txn_count"),
            pl.col("amount").sum().alias("txn_sum"),
            pl.col("amount").mean().alias("txn_avg"),
        )
    )
    device_counts = dict(
        dataset.accounts.group_by("device_fingerprint").len().iter_rows()
    )
    rows = _poc_rows(
        accounts["account_id"].to_list(),
        {r["account_id"]: r for r in accounts.iter_rows(named=True)},
        {r["src"]: r for r in aggregate.iter_rows(named=True)},
        device_counts,
        settings.sim_end_date,
    )
    scaler = StandardScaler().fit(rows)
    forest = IsolationForest(contamination=0.12, random_state=42).fit(scaler.transform(rows))
    return scaler, forest, device_counts


def _poc_rows(accounts, meta, aggregate, device_counts, as_of) -> np.ndarray:
    reference = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    rows = np.zeros((len(accounts), len(POC_FEATURES)), dtype=np.float64)
    for i, account in enumerate(accounts):
        record = meta[account]
        agg = aggregate.get(account)
        age = float((reference - record["open_date"]).days)
        count = float(agg["txn_count"]) if agg else 0.0
        total = float(agg["txn_sum"]) if agg else 0.0
        average = float(agg["txn_avg"]) if agg else 0.0
        rows[i] = [
            age,
            float(KYC_RISK.get(str(record["kyc_tier"]), 2)),
            float(device_counts.get(record["device_fingerprint"], 1)),
            count,
            total,
            average,
            count / (age + 1.0),
        ]
    return np.nan_to_num(rows, nan=0.0, posinf=0.0, neginf=0.0)


def score_poc(
    frame: CaseFrame, accounts: list[str], dataset, fitted
) -> tuple[dict[str, float], dict[str, list[dict]], dict[str, bool]]:
    """Their pipeline, run as written, ranked by their own risk_score.

    Their script produces two outputs: an IsolationForest anomaly flag at
    contamination 0.12, and a `risk_score` that their dashboard sorts by. The
    ranking here is theirs -- shared devices x10, velocity x100, degree
    centrality x200 -- and the IsolationForest flag becomes their native
    operating point, since contamination 0.12 *is* a published threshold.
    """
    scaler, forest, device_counts = fitted
    until = frame.complaint
    scope = set(accounts)

    aggregate = dict(
        (r["src"], r)
        for r in dataset.transactions.filter(
            (pl.col("timestamp") <= until) & pl.col("src").is_in(scope)
        )
        .group_by("src")
        .agg(
            pl.len().alias("txn_count"),
            pl.col("amount").sum().alias("txn_sum"),
            pl.col("amount").mean().alias("txn_avg"),
        )
        .iter_rows(named=True)
    )
    rows = _poc_rows(
        accounts, frame.meta, aggregate, device_counts, until.date()
    )
    anomaly = forest.predict(scaler.transform(rows)) == -1

    # Their network_score: undirected degree centrality on the transaction graph.
    graph = nx.Graph()
    graph.add_nodes_from(accounts)
    pairs = dataset.transactions.filter(
        (pl.col("timestamp") <= until)
        & pl.col("src").is_in(scope)
        & pl.col("dst").is_in(scope)
    ).select("src", "dst")
    for src, dst in pairs.iter_rows():
        if src != dst:
            graph.add_edge(src, dst)
    centrality = nx.degree_centrality(graph) if graph.number_of_nodes() else {}

    device_index = POC_FEATURES.index("shared_device_count")
    velocity_index = POC_FEATURES.index("velocity_score")

    raw: dict[str, tuple[float, float, float, float]] = {}
    for i, account in enumerate(accounts):
        device_part = rows[i, device_index] * 10.0
        velocity_part = rows[i, velocity_index] * 100.0
        network_part = centrality.get(account, 0.0) * 200.0
        raw[account] = (
            device_part + velocity_part + network_part,
            device_part,
            velocity_part,
            network_part,
        )

    position = {a: i for i, a in enumerate(accounts)}
    ceiling = max((v[0] for v in raw.values()), default=1.0) or 1.0
    scores: dict[str, float] = {}
    signals: dict[str, list[dict]] = {}
    for account, (total, device_part, velocity_part, network_part) in raw.items():
        scores[account] = round(clamp(total / ceiling, 0.0, 1.0), 6)
        parts = [
            ("shared_device_count", device_part, f"Shares a device with {int(rows[position[account], device_index])} accounts in the population"),
            ("velocity_score", velocity_part, "Transfers per day of account age"),
            ("network_score", network_part, "Degree centrality in the transaction graph"),
        ]
        parts.sort(key=lambda p: -p[1])
        denominator = sum(max(p[1], 0.0) for p in parts) or 1.0
        signals[account] = [
            {
                "feature": name,
                "contribution": round(max(value, 0.0) / denominator, 4),
                "direction": "up",
                "human_text": text,
            }
            for name, value, text in parts[:3]
        ]
    flags = {account: bool(anomaly[i]) for i, account in enumerate(accounts)}
    return scores, signals, flags


# ---------------------------------------------------------------------------
# operating points
# ---------------------------------------------------------------------------


def operating_points(
    scores: dict[str, float],
    truth: dict[str, bool],
    budget: int,
    native_threshold: float | None,
    native_flags: dict[str, bool] | None,
    target_fpr: float,
) -> dict[str, dict]:
    """The same three cuts for every model, computed here and stored.

    The Arena switches between them by re-reading a stored budget or threshold.
    It never adjusts a score, and it never computes a threshold of its own.
    """
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))

    budget_threshold = ranked[min(budget, len(ranked)) - 1][1] if ranked else 1.0

    # equal_fpr: the threshold at which this model flags `target_fpr` of the
    # innocent accounts in this case. Every model is held to the same rate, so
    # a model that buys recall with collateral damage cannot hide it here.
    innocent = sorted(
        (score for account, score in scores.items() if not truth.get(account, False)),
        reverse=True,
    )
    if innocent:
        allowed = max(0, int(round(target_fpr * len(innocent))))
        fpr_threshold = innocent[allowed - 1] if allowed >= 1 else innocent[0] + 1e-9
    else:
        fpr_threshold = 1.0

    if native_flags is not None:
        flagged = [scores[a] for a, on in native_flags.items() if on]
        native = min(flagged) if flagged else 1.0
    else:
        native = native_threshold if native_threshold is not None else 0.5

    return {
        "equal_alert_budget": {
            "mode": "equal_alert_budget",
            "budget": budget,
            "threshold": round(float(budget_threshold), 6),
            "calibration_note": (
                f"All four systems may flag at most {budget} accounts on this case. "
                "A bank's investigation desk has a fixed daily capacity, so this is "
                "the comparison that matches how the alerts would actually be worked."
            ),
        },
        "equal_fpr": {
            "mode": "equal_fpr",
            "budget": len(ranked),
            "threshold": round(float(fpr_threshold), 6),
            "calibration_note": (
                f"Thresholds chosen per system so all four flag the same {target_fpr:.0%} "
                "of the innocent accounts in this case."
            ),
        },
        "native": {
            "mode": "native",
            "budget": len(ranked),
            "threshold": round(float(native), 6),
            "calibration_note": (
                "Each system at its own published threshold. The operating points "
                "differ, so the counts are not directly comparable -- which is the "
                "point of the other two modes."
            ),
        },
    }


def decisions_for(
    scores: dict[str, float],
    signals: dict[str, list[dict]],
    active: dict,
    complaint_offset: int,
) -> list[dict]:
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    budget = int(active["budget"])
    threshold = float(active["threshold"])

    out: list[dict] = []
    committed = 0
    for rank, (account, score) in enumerate(ranked, start=1):
        flag = rank <= budget and score >= threshold
        if flag:
            committed += 1
            wave = math.ceil(committed / DISPATCH_PARALLEL)
        else:
            # A cleared account still has a moment at which the system decided
            # not to act; it is the moment its queue position came up.
            wave = math.ceil(min(rank, budget + 1) / DISPATCH_PARALLEL)
        out.append(
            {
                "account_id": account,
                "score": round(float(score), 6),
                "rank": rank,
                "decision": "flag" if flag else "clear",
                "t_decision_sec": complaint_offset + wave * DISPATCH_LATENCY_SEC,
                "top_signals": signals.get(account, []),
            }
        )
    return out


# ---------------------------------------------------------------------------
# layout -- settled here so it never changes between runs
# ---------------------------------------------------------------------------


def layout(frame: CaseFrame, case_id: str) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """Layered radial in 3D, layered DAG in 2D.

    Both are settled with a short force relaxation and written into the case
    file. The Arena never runs a layout of its own, so the same case is
    pixel-identical on every reload and on every machine.
    """
    rand = mulberry32(seed_from(case_id))
    by_layer: dict[int, list[str]] = defaultdict(list)
    for account in frame.accounts:
        by_layer[frame.layer[account]].append(account)

    # Within a ring, order by bank so same-bank accounts cluster. That is what
    # makes "three banks" legible without a legend.
    for accounts in by_layer.values():
        accounts.sort(key=lambda a: (str(frame.meta[a]["bank_id"]), a))

    ring_radius, layer_height = 14.0, 9.0
    pos3: dict[str, np.ndarray] = {}
    pos2: dict[str, np.ndarray] = {}
    max_width = max(len(v) for v in by_layer.values())

    for depth in sorted(by_layer):
        accounts = by_layer[depth]
        radius = ring_radius * max(depth, 0) ** 0.86
        for i, account in enumerate(accounts):
            if depth == 0 and len(accounts) == 1:
                pos3[account] = np.array([0.0, 0.0, 0.0])
            else:
                angle = 2 * math.pi * (i + 0.5) / len(accounts) + 0.35 * depth
                jitter = (rand() - 0.5) * 0.16
                pos3[account] = np.array(
                    [
                        math.cos(angle + jitter) * radius * (1 + (rand() - 0.5) * 0.08),
                        -depth * layer_height,
                        math.sin(angle + jitter) * radius * (1 + (rand() - 0.5) * 0.08),
                    ]
                )
            span = max(len(accounts), 1)
            pos2[account] = np.array(
                [
                    (i + 0.5) / span * max_width * 5.6 - max_width * 2.8,
                    -depth * layer_height * 1.15,
                ]
            )

    # A short spring relaxation, constrained to the layer's ring / band. Ten
    # passes is enough to unpick crossings without letting a node drift out of
    # its layer -- the layer *is* the reading of the picture.
    neighbours: dict[str, list[str]] = defaultdict(list)
    for edge in list(frame.transfers) + list(frame.context_edges):
        neighbours[edge["from"]].append(edge["to"])
        neighbours[edge["to"]].append(edge["from"])

    for _ in range(10):
        for depth in sorted(by_layer):
            accounts = by_layer[depth]
            if depth == 0 or len(accounts) < 2:
                continue
            radius = ring_radius * depth**0.86
            for account in accounts:
                peers = [p for p in neighbours.get(account, ()) if p in pos3]
                if not peers:
                    continue
                target3 = np.mean([pos3[p] for p in peers], axis=0)
                point = pos3[account] + 0.25 * (target3 - pos3[account])
                flat = np.array([point[0], point[2]])
                norm = np.linalg.norm(flat) or 1.0
                flat = flat / norm * radius
                pos3[account] = np.array([flat[0], -depth * layer_height, flat[1]])

                target2 = float(np.mean([pos2[p][0] for p in peers]))
                pos2[account][0] += 0.3 * (target2 - pos2[account][0])

    return (
        {a: [round(float(v), 3) for v in pos3[a]] for a in frame.accounts},
        {a: [round(float(v), 3) for v in pos2[a]] for a in frame.accounts},
    )


# ---------------------------------------------------------------------------
# assembling one case
# ---------------------------------------------------------------------------


def classify(frame: CaseFrame) -> tuple[str, str]:
    """Scenario type and difficulty, both derived from the case rather than typed."""
    mules = [a for a in frame.accounts if frame.truth[a]]
    rings = defaultdict(int)
    for account in mules:
        ring = str(frame.meta[account].get("ring_id") or "")
        if ring:
            rings[ring] += 1

    scenario = TYPOLOGY_TO_SCENARIO.get(frame.incident.typology, "layering")
    if len(rings) >= 2 and sorted(rings.values())[-2] >= max(2, 0.2 * len(mules)):
        scenario = "mixed"
    elif mules:
        as_of = frame.complaint.date()
        dormant = sum(
            1
            for a in mules
            if (as_of - frame.meta[a]["prior_activity_date"]).days >= 90
        )
        if dormant / len(mules) >= 0.8:
            scenario = "dormant_reactivation"

    depth = max(frame.layer.values()) if frame.layer else 1
    escaped = sum(
        c["amount_inr"]
        for c in frame.cashouts
        if c["t_offset_sec"] <= (frame.complaint - frame.t0).total_seconds()
    )
    pressure = (
        frame.incident.complaint_delay_minutes / 60.0
        + depth / 4.0
        + 3.0 * escaped / max(frame.incident.amount_inr, 1.0)
    )
    difficulty = "easy" if pressure < 1.2 else ("medium" if pressure < 2.4 else "hard")
    return scenario, difficulty


def build_case(
    selection: Selection,
    dataset,
    index,
    poc_fitted,
    mh_fitted,
    known_mules: set[str],
    budget: int,
) -> dict | None:
    incident = selection.incident
    frame = build_frame(incident, dataset, index)
    if frame is None:
        log.warning("%s: too few accounts touched, skipping", incident.incident_id)
        return None

    complaint_offset = int((frame.complaint - frame.t0).total_seconds())
    victim = incident.victim_account
    victim_bank = str(frame.meta[victim]["bank_id"])

    # ---- the four systems, over the whole candidate frontier -------------
    #
    # This is the honest order of operations: every system scores the same few
    # hundred accounts, and only then does the exporter decide what to draw.
    # Choosing the picture first and scoring inside it would quietly delete the
    # false positives, which are half of what the scorecard is for.
    pool = frame.pool
    matrix = build_features(
        pool, incident.victim_account, frame.complaint, dataset, index
    )
    feats = arena_features(frame, pool, matrix, dataset, index)

    ours_scores, ours_signals = score_ours(frame, matrix, feats)
    argus_scores, argus_signals = score_argus_prism(frame, pool, dataset, feats)
    mh_scores, mh_signals = score_mule_hunter(
        frame, pool, dataset, mh_fitted, known_mules
    )
    poc_scores, poc_signals, poc_flags = score_poc(frame, pool, dataset, poc_fitted)

    # Nobody scores the victim: the victim is not a suspect, and leaving them in
    # the ranking would hand every model a free true negative.
    for table in (ours_scores, argus_scores, mh_scores, poc_scores):
        table.pop(victim, None)

    target_fpr = 0.12
    specs = [
        (
            "mulehunter",
            "MuleHunter (ours)",
            "ours",
            "LightGBM over 37 incident features, including five that are properties of an account's neighbourhood rather than of the account.",
            "The model in backend/models/gbdt.txt, scored on features computed as of the complaint time. Attributions are exact SHAP values from the booster.",
            ours_scores,
            ours_signals,
            None,
            None,
        ),
        (
            "argus_prism",
            "ARGUS-PRISM WarmthScore",
            "baseline",
            "Six weighted behavioural signals -- velocity, round-trip, structuring, dormant-device, profile mismatch, SIM swap.",
            "Their six signal functions and their published weights, reimplemented from ARGUS-PRISM/backend/app/engines/warmthscore/signals.py and evaluated as of the complaint time instead of the wall clock. Their SIM-swap signal needs a telco feed this dataset does not have, so 10 of their 100 points are unavailable in every case.",
            argus_scores,
            argus_signals,
            0.5,
            None,
        ),
        (
            "mule_hunter_gnn",
            "MULE_HUNTER graph model",
            "baseline",
            "Graph-topology features -- PageRank, reciprocity, ring membership, community and second-hop fraud rate.",
            "Their feature set, computed exactly as their feature_engineering.py computes it. Their SAGE->GAT network needs torch_geometric and its own training corpus, neither of which travels with this repo, so the features are read by a logistic model fitted on training-ring incidents. Their features, our learner -- and their two guilt-by-association features are computed from accounts already known to be mules, which is what a deployed version would actually see.",
            mh_scores,
            mh_signals,
            0.5,
            None,
        ),
        (
            "poc_isoforest",
            "Mule-Account PoC (Isolation Forest)",
            "baseline",
            "Isolation Forest over seven account features, ranked by shared devices, velocity and degree centrality.",
            "Run as written: the same seven features, StandardScaler, IsolationForest(contamination=0.12, random_state=42) and their own risk_score ranking formula. Their contamination setting is a published threshold, so it becomes their native operating point.",
            poc_scores,
            poc_signals,
            None,
            poc_flags,
        ),
    ]

    models: list[dict] = []
    all_decisions: list[tuple[str, list[dict]]] = []
    for (
        model_id,
        name,
        family,
        one_liner,
        method_note,
        scores,
        signals,
        native_threshold,
        native_flags,
    ) in specs:
        native_flags = (
            {a: v for a, v in native_flags.items() if a in scores} if native_flags else None
        )
        points = operating_points(
            scores, frame.truth, budget, native_threshold, native_flags, target_fpr
        )
        active = points["equal_alert_budget"]
        decisions = decisions_for(scores, signals, active, complaint_offset)
        all_decisions.append((model_id, decisions))
        models.append(
            {
                "id": model_id,
                "name": name,
                "family": family,
                "one_liner": one_liner,
                "method_note": method_note,
                "operating_point": active,
                "operating_points": points,
                "decisions": decisions,
            }
        )

    # ---- now decide what gets drawn -------------------------------------
    #
    # Every account any system flagged under any of the three operating points
    # is on screen. A false positive nobody can see is a false positive nobody
    # believes.
    must_show: set[str] = set()
    for model, (_, decisions) in zip(models, all_decisions):
        by_account = {d["account_id"]: d for d in decisions}
        for point in model["operating_points"].values():
            for decision in decisions:
                if (
                    decision["rank"] <= point["budget"]
                    and decision["score"] >= point["threshold"]
                ):
                    must_show.add(decision["account_id"])
        must_show.update(
            d["account_id"] for d in decisions if d["decision"] == "flag"
        )
        del by_account

    choose_visible(frame, must_show, dataset)
    visible = set(frame.accounts)

    scenario_type, difficulty = classify(frame)
    balances = own_balances(frame, dataset)
    pos3, pos2 = layout(frame, selection.case_id)

    # Ranks and thresholds came from the whole pool; only the drawn slice is
    # written out. The `pool_size` field records what was really scored so the
    # confusion matrix on screen can say what it is a matrix over.
    for model in models:
        model["pool_size"] = len(pool)
        model["decisions"] = [
            d for d in model["decisions"] if d["account_id"] in visible
        ]

    accounts = [
        {
            "id": account,
            "display_id": display_id(account, str(frame.meta[account]["bank_id"])),
            "bank": str(frame.meta[account]["bank_id"]),
            "layer": frame.layer[account],
            "balance_before_inr": balances[account],
            "opened_at": frame.meta[account]["open_date"].isoformat(),
            "kyc_level": {"full": "full", "small": "min", "video": "video", "none": "none"}[
                str(frame.meta[account]["kyc_tier"])
            ],
            "ground_truth": "mule" if frame.truth[account] else "innocent",
            "pos": pos3[account],
            "pos2": pos2[account],
            "features": feats[account],
        }
        for account in frame.accounts
    ]

    hops = max(frame.layer.values()) if frame.layer else 1
    banks = len({a["bank"] for a in accounts})
    case = {
        "schema_version": SCHEMA_VERSION,
        "case_id": selection.case_id,
        "title": _title(incident, hops, banks),
        "scenario_type": scenario_type,
        "difficulty": difficulty,
        "data_provenance": "holdout"
        if incident.ring_id in set(settings.holdout_ring_ids)
        else "synthetic",
        "t0": frame.t0.isoformat(),
        "horizon_sec": int((frame.horizon - frame.t0).total_seconds()),
        "complaint_offset_sec": complaint_offset,
        # Where the replay actually ends. The horizon is six hours, but nothing
        # happens in the last five of them and a scrubber that spends most of
        # its travel on an empty timeline is a scrubber nobody can use.
        "t_end_sec": max(
            [complaint_offset]
            + [t["t_offset_sec"] for t in frame.transfers]
            + [c["t_offset_sec"] for c in frame.cashouts]
            + [
                d["t_decision_sec"]
                for m in models
                for d in m["decisions"]
                if d["decision"] == "flag"
            ]
        )
        + 240,
        "provenance": {
            "episode_id": incident.episode_id,
            "ring_id": incident.ring_id,
            "typology": incident.typology,
            "generator_seed": settings.master_seed,
            "exported_by": "tools/export_case.py",
            "exporter_version": EXPORTER_VERSION,
        },
        "victim": {
            "account_id": victim,
            "display_id": display_id(victim, victim_bank),
            "amount_inr": round(float(incident.amount_inr), 2),
            "channel": frame.transfers[0]["channel"] if frame.transfers else "IMPS",
        },
        "accounts": accounts,
        "transfers": frame.transfers,
        "context_edges": frame.context_edges,
        "cashout_events": frame.cashouts,
        "models": models,
        "recovery_model": {
            "type": "linear_drain",
            "description": (
                "Stolen funds become unrecoverable as they are forwarded onward or "
                "cashed out. Freezing an account at time t recovers the stolen money "
                "still sitting in it at t. Freezing also locks the holder's own "
                "balance, which is what the wrongly-frozen figure prices."
            ),
            "settlement_lag_sec": 0,
        },
    }
    case["weakness_note"] = weakness_note(case)
    return case


def _title(incident: Incident, hops: int, banks: int) -> str:
    shape = {
        "fanout": "Fan-out layering",
        "structuring": "Sub-threshold structuring",
        "chain_burst": "Narrow chain into a burst",
        "crypto_exit": "Crypto exit",
    }.get(incident.typology, incident.typology.replace("_", " ").title())
    return f"{shape}, {hops} hops, {banks} banks"


# ---------------------------------------------------------------------------
# scoring the case, for the Act 6 weakness note
# ---------------------------------------------------------------------------


def evaluate(case: dict, lam: float = 1.0) -> dict[str, dict]:
    """The Arena's metric definitions, recomputed here so the note is measured.

    This is the same arithmetic the Arena does at render time; running it here
    as well is a cheap cross-check that the two agree.
    """
    truth = {a["id"]: a["ground_truth"] for a in case["accounts"]}
    own = {a["id"]: a["balance_before_inr"] for a in case["accounts"]}
    layer = {a["id"]: a["layer"] for a in case["accounts"]}

    events: list[tuple[int, str, float]] = []
    for transfer in case["transfers"]:
        events.append((transfer["t_offset_sec"], transfer["to"], transfer["amount_inr"]))
        events.append((transfer["t_offset_sec"], transfer["from"], -transfer["amount_inr"]))
    for cashout in case["cashout_events"]:
        events.append((cashout["t_offset_sec"], cashout["account_id"], -cashout["amount_inr"]))
    events.sort(key=lambda e: e[0])

    def tainted_at(account: str, t: int) -> float:
        held = case["victim"]["amount_inr"] if account == case["victim"]["account_id"] else 0.0
        for when, who, delta in events:
            if when > t:
                break
            if who == account:
                held += delta
        return max(0.0, held)

    out: dict[str, dict] = {}
    for model in case["models"]:
        recovered = wrongly = 0.0
        tp = fp = fn = tn = 0
        latencies: list[int] = []
        first_hop = None
        for decision in model["decisions"]:
            account = decision["account_id"]
            is_mule = truth[account] == "mule"
            flagged = decision["decision"] == "flag"
            if flagged and is_mule:
                tp += 1
                recovered += tainted_at(account, decision["t_decision_sec"])
                latencies.append(decision["t_decision_sec"])
                first_hop = layer[account] if first_hop is None else min(first_hop, layer[account])
            elif flagged:
                fp += 1
                wrongly += own[account] + tainted_at(account, decision["t_decision_sec"])
            elif is_mule:
                fn += 1
            else:
                tn += 1
        out[model["id"]] = {
            "recovered": round(recovered, 2),
            "wrongly_frozen": round(wrongly, 2),
            "customers_impacted": fp,
            "net_benefit": round(recovered - lam * wrongly, 2),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "median_latency_sec": int(np.median(latencies)) if latencies else None,
            "first_flag_hop": first_hop,
        }
    return out


def weakness_note(case: dict) -> str:
    """Act 6, written from the measured result rather than by hand."""
    result = evaluate(case)
    ours = result["mulehunter"]
    rivals = {k: v for k, v in result.items() if k != "mulehunter"}
    names = {m["id"]: m["name"] for m in case["models"]}

    better = [k for k, v in rivals.items() if v["net_benefit"] > ours["net_benefit"]]
    if better:
        top = max(better, key=lambda k: rivals[k]["net_benefit"])
        return (
            f"{names[top]} beats us on this case on net benefit "
            f"(₹{rivals[top]['net_benefit']:,.0f} against ₹{ours['net_benefit']:,.0f}). "
            + (
                f"We missed {ours['fn']} mule account(s) it caught."
                if ours["fn"] > rivals[top]["fn"]
                else f"We froze {ours['fp']} innocent account(s) against its {rivals[top]['fp']}."
            )
        )
    if ours["fn"]:
        deepest = ours["first_flag_hop"]
        return (
            f"We win this case on net benefit but still miss {ours['fn']} mule account(s). "
            f"Our earliest correct flag lands at hop {deepest}; anything the money reached "
            "before that is already spent by the time the freeze arrives."
        )
    if ours["fp"]:
        return (
            f"We win this case, but {ours['fp']} innocent account(s) were frozen with it, "
            f"locking ₹{ours['wrongly_frozen']:,.0f} of somebody else's money. "
            "That cost is on the scorecard at the same weight as the recovery."
        )
    return (
        "No system beats us on this case and we neither missed a mule nor froze an "
        "innocent account. That is the easy end of the distribution -- look at the "
        "harder cases before believing it."
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO / "data" / "cases")
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("--case", type=str, default=None, help="export one episode or scenario id")
    args = parser.parse_args(argv)

    dataset = load_dataset()
    index = transaction_index()

    # The watchlist a deployed system would have: accounts already known to be
    # mules from previously worked cases. Held-out rings are, by construction,
    # not on it -- which is the whole point of holding them out.
    held = set(settings.holdout_ring_ids)
    known_mules = set(
        dataset.labels.filter(pl.col("is_mule") & ~pl.col("ring_id").is_in(held))[
            "account_id"
        ].to_list()
    )
    log.info("watchlist: %d accounts from training rings", len(known_mules))

    selections = select_incidents(args.count, args.case)
    log.info("exporting %d cases", len(selections))

    training = [i for i in episodes_for(holdout=False) if i.complaint_delay_minutes <= 130]
    training.sort(key=lambda i: i.episode_id)
    log.info("fitting baselines...")
    mh_fitted = fit_mule_hunter(dataset, index, known_mules, training[:14])
    poc_fitted = fit_poc(dataset)

    args.out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    written = 0

    for selection in selections:
        case = build_case(
            selection, dataset, index, poc_fitted, mh_fitted, known_mules, args.budget
        )
        if case is None:
            continue
        path = args.out / f"{selection.case_id}.json"
        path.write_text(json.dumps(case, indent=1, default=str), encoding="utf-8")
        written += 1

        result = evaluate(case)
        ours = result["mulehunter"]
        best = max(result, key=lambda k: result[k]["net_benefit"])
        log.info(
            "  %s  %-38s %-20s %-9s ours net ₹%10.0f  best=%s  TP%d FP%d FN%d",
            selection.case_id,
            case["title"][:38],
            case["scenario_type"],
            case["data_provenance"],
            ours["net_benefit"],
            best,
            ours["tp"],
            ours["fp"],
            ours["fn"],
        )
        manifest.append(
            {
                "case_id": case["case_id"],
                "file": f"cases/{selection.case_id}.json",
                "title": case["title"],
                "scenario_type": case["scenario_type"],
                "difficulty": case["difficulty"],
                "data_provenance": case["data_provenance"],
                "amount_inr": case["victim"]["amount_inr"],
                "accounts": len(case["accounts"]),
                "hops": max(a["layer"] for a in case["accounts"]),
                "banks": len({a["bank"] for a in case["accounts"]}),
                "we_get_it_wrong": bool(ours["fn"] or ours["fp"]),
                "best_model": best,
            }
        )

    (args.out.parent / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "exporter_version": EXPORTER_VERSION,
                "generated_from": "backend/data (synthetic, seed %d)" % settings.master_seed,
                "cases": manifest,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    log.info("wrote %d cases + manifest to %s", written, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
