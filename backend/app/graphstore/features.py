"""Node feature engineering for the incident subgraph.

Every feature here is computed from transactions **at or before the complaint
time**, and from account attributes a bank already holds. Nothing reads the
future and nothing reads a label. That restriction is the whole reason the
benchmark numbers mean anything.

The features are grouped the way an analyst would reason about them:

* **velocity** -- how fast money passes through. Mules hold funds for minutes.
* **structure** -- position in the graph. Being a bottleneck matters more than
  being busy.
* **temporal** -- dormancy, account age, burstiness, night activity.
* **amount** -- structuring tells, split regularity, round numbers.
* **shared infrastructure** -- device and IP clusters, recipient overlap,
  co-ordinated account openings. This group is the one a per-account rule
  engine cannot see, because none of it is a property of the account alone.
* **cash-out proximity** -- how close the account sits to an exit.

The hard-negative check in `contrast_report` exists because of one specific
failure: legitimate high-velocity accounts (chit fund operators, travel agents)
score *high* on every velocity feature. A detector that leans on velocity will
flag them and be useless. They must separate on shared infrastructure instead,
and the report prints that separation rather than assuming it.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import networkx as nx
import numpy as np
import polars as pl

from app.config import settings
from app.graphstore.build import Dataset, load_dataset
from app.graphstore.trace import TransactionIndex, to_epoch, transaction_index

log = logging.getLogger(__name__)

#: Feature order is part of the model contract. Appending is safe; reordering
#: or removing invalidates every saved model, so retrain if you touch this.
FEATURE_NAMES: tuple[str, ...] = (
    # velocity
    "median_residence_minutes",
    "in_out_ratio_1h",
    "in_out_ratio_6h",
    "in_out_ratio_24h",
    "turnover_ratio",
    "outflow_within_10min_share",
    "max_fanout_10min",
    # structure
    "in_degree",
    "out_degree",
    "fanout_ratio",
    "pagerank",
    "betweenness",
    "hops_from_victim",
    "hops_to_exit",
    "reciprocity",
    # temporal
    "dormancy_days",
    "account_age_days",
    "burstiness",
    "night_activity_share",
    "activity_span_hours",
    # amount
    "structuring_band_share",
    "amount_cv",
    "round_amount_share",
    "log_max_credit",
    "log_total_out",
    "txn_count",
    # shared infrastructure
    "device_cluster_size",
    "ip_cluster_size",
    "recipient_jaccard_max",
    "same_window_openings",
    "device_peers_in_incident",
    # cash-out proximity
    "atm_value_share",
    "exchange_flag",
    "crossborder_flag",
    "exit_adjacent",
    # account attributes
    "kyc_video_flag",
    "kyc_small_flag",
)

N_FEATURES: int = len(FEATURE_NAMES)

#: Plain-language names, used by the explainability drawer. A judge should not
#: have to read `structuring_band_share` and work out what it means.
FEATURE_LABELS: dict[str, str] = {
    "median_residence_minutes": "how long money sits before moving on",
    "in_out_ratio_1h": "money out vs in, last hour",
    "in_out_ratio_6h": "money out vs in, last six hours",
    "in_out_ratio_24h": "money out vs in, last day",
    "turnover_ratio": "share of everything received that was forwarded",
    "outflow_within_10min_share": "transfers forwarded within ten minutes",
    "max_fanout_10min": "most recipients paid inside any ten-minute window",
    "in_degree": "accounts it receives from",
    "out_degree": "accounts it sends to",
    "fanout_ratio": "recipients per sender",
    "pagerank": "centrality in the incident graph",
    "betweenness": "how much traffic must pass through it",
    "hops_from_victim": "hops from the victim",
    "hops_to_exit": "hops to the nearest cash-out point",
    "reciprocity": "share of counterparties it both pays and is paid by",
    "dormancy_days": "days dormant before it woke up",
    "account_age_days": "age of the account",
    "burstiness": "how clustered its activity is in time",
    "night_activity_share": "share of activity between 23:00 and 05:00",
    "activity_span_hours": "hours between its first and last transfer",
    "structuring_band_share": "transfers held just under ₹50,000",
    "amount_cv": "how uniform its outgoing amounts are",
    "round_amount_share": "transfers in round numbers",
    "log_max_credit": "largest single credit received",
    "log_total_out": "total value sent",
    "txn_count": "transfers in the window",
    "device_cluster_size": "accounts sharing its device",
    "ip_cluster_size": "accounts sharing its IP range",
    "recipient_jaccard_max": "overlap of its payee list with another account's",
    "same_window_openings": "neighbours opened in the same narrow window",
    "device_peers_in_incident": "accounts on its device that are also in this incident",
    "atm_value_share": "share of value withdrawn as cash",
    "exchange_flag": "sends to a crypto exchange deposit account",
    "crossborder_flag": "sends cross-border",
    "exit_adjacent": "one hop from a cash-out point",
    "kyc_video_flag": "opened by video KYC",
    "kyc_small_flag": "small (limited KYC) account",
}


@dataclass(frozen=True)
class FeatureMatrix:
    """Feature values for a set of accounts, in a fixed column order."""

    account_ids: tuple[str, ...]
    values: np.ndarray  # (n_accounts, N_FEATURES) float32
    names: tuple[str, ...] = FEATURE_NAMES

    def __post_init__(self) -> None:
        if self.values.shape != (len(self.account_ids), len(self.names)):
            raise ValueError(
                f"feature matrix is {self.values.shape}, expected "
                f"({len(self.account_ids)}, {len(self.names)})"
            )
        if not np.isfinite(self.values).all():
            bad = [
                self.names[c]
                for c in range(self.values.shape[1])
                if not np.isfinite(self.values[:, c]).all()
            ]
            raise ValueError(f"non-finite values in features: {bad}")

    @property
    def index(self) -> dict[str, int]:
        return {account: i for i, account in enumerate(self.account_ids)}

    def row(self, account_id: str) -> np.ndarray:
        return self.values[self.index[account_id]]

    def to_frame(self) -> pl.DataFrame:
        return pl.DataFrame(
            {"account_id": list(self.account_ids)}
            | {
                name: self.values[:, i].astype(np.float64)
                for i, name in enumerate(self.names)
            }
        )


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def build_features(
    accounts: list[str],
    victim: str,
    until: datetime,
    dataset: Dataset | None = None,
    index: TransactionIndex | None = None,
) -> FeatureMatrix:
    """Feature matrix for `accounts`, using only data visible at `until`."""
    ds = dataset if dataset is not None else load_dataset()
    idx = index if index is not None else transaction_index()

    order = list(accounts)
    position = {account: i for i, account in enumerate(order)}
    n = len(order)
    values = np.zeros((n, N_FEATURES), dtype=np.float64)
    if n == 0:
        return FeatureMatrix(account_ids=(), values=values.astype(np.float32))

    keep = set(order)
    edges = _visible_edges(ds, keep, until)

    columns = {name: i for i, name in enumerate(FEATURE_NAMES)}
    _flow_features(edges, position, values, columns, until)
    _amount_features(edges, position, values, columns, idx)
    _structural_features(edges, position, values, columns, keep, victim, idx)
    _account_features(ds, order, position, values, columns, edges, until)

    values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    return FeatureMatrix(
        account_ids=tuple(order), values=values.astype(np.float32)
    )


def _visible_edges(dataset: Dataset, keep: set[str], until: datetime) -> pl.DataFrame:
    """Transactions at or before `until` that touch the candidate set."""
    return (
        dataset.transactions.lazy()
        .filter(pl.col("timestamp") <= until)
        .filter(pl.col("src").is_in(keep) | pl.col("dst").is_in(keep))
        .select("src", "dst", "amount", "timestamp", "channel")
        .with_columns(pl.col("timestamp").dt.epoch(time_unit="s").alias("epoch"))
        .collect()
    )


# ---------------------------------------------------------------------------
# velocity and temporal
# ---------------------------------------------------------------------------


def _flow_features(
    edges: pl.DataFrame,
    position: dict[str, int],
    values: np.ndarray,
    columns: dict[str, int],
    until: datetime,
) -> None:
    end = to_epoch(until)

    outgoing = edges.filter(pl.col("src").is_in(position.keys()))
    incoming = edges.filter(pl.col("dst").is_in(position.keys()))

    out_agg = outgoing.group_by("src").agg(
        pl.col("amount").sum().alias("out_value"),
        pl.len().alias("out_count"),
        pl.col("dst").n_unique().alias("out_degree"),
        pl.col("epoch").min().alias("first_out"),
        pl.col("epoch").max().alias("last_out"),
    )
    in_agg = incoming.group_by("dst").agg(
        pl.col("amount").sum().alias("in_value"),
        pl.col("amount").max().alias("max_credit"),
        pl.len().alias("in_count"),
        pl.col("src").n_unique().alias("in_degree"),
        pl.col("epoch").min().alias("first_in"),
    )

    out_value = np.zeros(len(position))
    in_value = np.zeros(len(position))

    for row in out_agg.iter_rows(named=True):
        i = position[row["src"]]
        out_value[i] = row["out_value"]
        values[i, columns["out_degree"]] = row["out_degree"]
        values[i, columns["log_total_out"]] = math.log1p(row["out_value"])
        values[i, columns["txn_count"]] = row["out_count"]
        values[i, columns["activity_span_hours"]] = (
            row["last_out"] - row["first_out"]
        ) / 3600.0

    for row in in_agg.iter_rows(named=True):
        i = position[row["dst"]]
        in_value[i] = row["in_value"]
        values[i, columns["in_degree"]] = row["in_degree"]
        values[i, columns["log_max_credit"]] = math.log1p(row["max_credit"])
        values[i, columns["txn_count"]] += row["in_count"]

    # Turnover and fan-out. A mule forwards essentially everything it receives.
    values[:, columns["turnover_ratio"]] = out_value / np.maximum(in_value, 1.0)
    values[:, columns["fanout_ratio"]] = values[:, columns["out_degree"]] / np.maximum(
        values[:, columns["in_degree"]], 1.0
    )

    # Rolling in/out ratios. These are the features legitimate high-velocity
    # accounts also score highly on -- deliberately kept, so the model has to
    # find something better.
    for hours in settings.feature_windows_hours:
        cutoff = end - hours * 3600
        window_out = (
            outgoing.filter(pl.col("epoch") >= cutoff)
            .group_by("src")
            .agg(pl.col("amount").sum())
        )
        window_in = (
            incoming.filter(pl.col("epoch") >= cutoff)
            .group_by("dst")
            .agg(pl.col("amount").sum())
        )
        sent = np.zeros(len(position))
        received = np.zeros(len(position))
        for row in window_out.iter_rows(named=True):
            sent[position[row["src"]]] = row["amount"]
        for row in window_in.iter_rows(named=True):
            received[position[row["dst"]]] = row["amount"]
        values[:, columns[f"in_out_ratio_{hours}h"]] = sent / np.maximum(received, 1.0)

    _residence_features(edges, position, values, columns)
    _burst_fanout(outgoing, position, values, columns)


def _burst_fanout(
    outgoing: pl.DataFrame,
    position: dict[str, int],
    values: np.ndarray,
    columns: dict[str, int],
) -> None:
    """Most distinct recipients paid inside any ten-minute window.

    Computed exactly rather than approximated, because the rules baseline is
    defined in terms of it and a strawman built from a proxy is not a fair
    comparison -- the whole point of keeping the rules tier is that its numbers
    have to be defensible too.
    """
    if outgoing.height == 0:
        return

    window = timedelta(minutes=settings.rule_fanout_window_minutes)
    rolled = (
        outgoing.sort("timestamp")
        .rolling(index_column="timestamp", period=window, group_by="src")
        .agg(pl.col("dst").n_unique().alias("recipients"))
        .group_by("src")
        .agg(pl.col("recipients").max().alias("peak"))
    )
    for row in rolled.iter_rows(named=True):
        values[position[row["src"]], columns["max_fanout_10min"]] = float(row["peak"])


def _residence_features(
    edges: pl.DataFrame,
    position: dict[str, int],
    values: np.ndarray,
    columns: dict[str, int],
) -> None:
    """How long money sits in an account before it moves on.

    For each debit, look back to the most recent credit on the same account.
    A mule's answer is minutes; a salary account's is days. An as-of join does
    this for the whole population at once.
    """
    credits = (
        edges.filter(pl.col("dst").is_in(position.keys()))
        .select(
            pl.col("dst").alias("account"),
            pl.col("epoch").alias("credit_epoch"),
        )
        .sort("credit_epoch")
    )
    debits = (
        edges.filter(pl.col("src").is_in(position.keys()))
        .select(
            pl.col("src").alias("account"),
            pl.col("epoch").alias("debit_epoch"),
        )
        .sort("debit_epoch")
    )
    if credits.height == 0 or debits.height == 0:
        return

    matched = debits.join_asof(
        credits,
        left_on="debit_epoch",
        right_on="credit_epoch",
        by="account",
        strategy="backward",
    ).drop_nulls("credit_epoch")
    if matched.height == 0:
        return

    matched = matched.with_columns(
        ((pl.col("debit_epoch") - pl.col("credit_epoch")) / 60.0).alias("residence")
    )
    summary = matched.group_by("account").agg(
        pl.col("residence").median().alias("median_residence"),
        (pl.col("residence") <= 10.0).mean().alias("fast_share"),
        pl.col("residence").std().alias("residence_std"),
        pl.col("residence").mean().alias("residence_mean"),
    )

    for row in summary.iter_rows(named=True):
        i = position[row["account"]]
        values[i, columns["median_residence_minutes"]] = row["median_residence"] or 0.0
        values[i, columns["outflow_within_10min_share"]] = row["fast_share"] or 0.0
        # Fano factor: variance over mean of the gaps. Bursty activity -- long
        # silence, then a flurry -- scores high. Steady traffic scores near one.
        mean = row["residence_mean"] or 0.0
        std = row["residence_std"] or 0.0
        values[i, columns["burstiness"]] = (std * std) / mean if mean > 0 else 0.0


# ---------------------------------------------------------------------------
# amounts and cash-out proximity
# ---------------------------------------------------------------------------


def _amount_features(
    edges: pl.DataFrame,
    position: dict[str, int],
    values: np.ndarray,
    columns: dict[str, int],
    index: TransactionIndex,
) -> None:
    lo, hi = settings.structuring_band_inr
    night_start, night_end = settings.night_hours

    outgoing = edges.filter(pl.col("src").is_in(position.keys()))
    if outgoing.height == 0:
        return

    exits = index.exits
    exchange = {a for a, kind in index.exit_kind.items() if kind == "exchange"}
    crossborder = {a for a, kind in index.exit_kind.items() if kind == "crossborder"}

    enriched = outgoing.with_columns(
        pl.col("amount").is_between(lo, hi).alias("in_band"),
        (pl.col("amount") % 1000.0 == 0.0).alias("is_round"),
        (pl.col("channel") == "ATM_WITHDRAWAL").alias("is_atm"),
        pl.col("dst").is_in(exits).alias("to_exit"),
        pl.col("dst").is_in(exchange).alias("to_exchange"),
        pl.col("dst").is_in(crossborder).alias("to_crossborder"),
        pl.col("timestamp").dt.hour().alias("hour"),
    ).with_columns(
        (
            (pl.col("hour") >= night_start) | (pl.col("hour") < night_end)
        ).alias("is_night")
    )

    summary = enriched.group_by("src").agg(
        pl.col("in_band").mean().alias("band_share"),
        pl.col("is_round").mean().alias("round_share"),
        pl.col("is_night").mean().alias("night_share"),
        (pl.col("amount") * pl.col("is_atm")).sum().alias("atm_value"),
        pl.col("amount").sum().alias("total_value"),
        pl.col("amount").mean().alias("mean_amount"),
        pl.col("amount").std().alias("std_amount"),
        pl.col("to_exit").any().alias("exit_adjacent"),
        pl.col("to_exchange").any().alias("exchange_flag"),
        pl.col("to_crossborder").any().alias("crossborder_flag"),
    )

    for row in summary.iter_rows(named=True):
        i = position[row["src"]]
        values[i, columns["structuring_band_share"]] = row["band_share"] or 0.0
        values[i, columns["round_amount_share"]] = row["round_share"] or 0.0
        values[i, columns["night_activity_share"]] = row["night_share"] or 0.0
        total = row["total_value"] or 0.0
        values[i, columns["atm_value_share"]] = (
            (row["atm_value"] or 0.0) / total if total > 0 else 0.0
        )
        mean = row["mean_amount"] or 0.0
        std = row["std_amount"] or 0.0
        # Near-equal splits are a laundering tell; a low coefficient of
        # variation across many transfers is hard to produce by accident.
        values[i, columns["amount_cv"]] = std / mean if mean > 0 else 0.0
        values[i, columns["exit_adjacent"]] = float(row["exit_adjacent"])
        values[i, columns["exchange_flag"]] = float(row["exchange_flag"])
        values[i, columns["crossborder_flag"]] = float(row["crossborder_flag"])


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------


def _structural_features(
    edges: pl.DataFrame,
    position: dict[str, int],
    values: np.ndarray,
    columns: dict[str, int],
    keep: set[str],
    victim: str,
    index: TransactionIndex,
) -> None:
    """Graph position: centrality, distance from the victim, distance to an exit."""
    induced = edges.filter(pl.col("src").is_in(keep) & pl.col("dst").is_in(keep))

    graph = nx.DiGraph()
    graph.add_nodes_from(position)
    weights = (
        induced.group_by(["src", "dst"]).agg(pl.col("amount").sum()).iter_rows()
    )
    for src, dst, amount in weights:
        graph.add_edge(src, dst, weight=float(amount))

    if graph.number_of_edges() == 0:
        return

    for node, score in nx.pagerank(graph, alpha=0.85, weight="weight").items():
        values[position[node], columns["pagerank"]] = score

    # Exact betweenness is O(nm) and would blow the latency budget on a graph
    # this size. Sampling 64 pivots is accurate enough to rank bottlenecks, and
    # the fixed seed keeps it reproducible run to run.
    pivots = min(64, graph.number_of_nodes())
    between = nx.betweenness_centrality(
        graph, k=pivots, seed=settings.master_seed, normalized=True
    )
    for node, score in between.items():
        values[position[node], columns["betweenness"]] = score

    # Reciprocity: ordinary people pay the people who pay them. Laundering
    # chains are one-directional, so a mule's reciprocity is near zero.
    for node, i in position.items():
        successors = set(graph.successors(node))
        predecessors = set(graph.predecessors(node))
        both = successors | predecessors
        if both:
            values[i, columns["reciprocity"]] = len(successors & predecessors) / len(both)

    _distance_features(graph, position, values, columns, victim, index, edges)


def _distance_features(
    graph: nx.DiGraph,
    position: dict[str, int],
    values: np.ndarray,
    columns: dict[str, int],
    victim: str,
    index: TransactionIndex,
    edges: pl.DataFrame,
) -> None:
    unreachable = 99.0

    from_victim = (
        nx.single_source_shortest_path_length(graph, victim)
        if victim in graph
        else {}
    )
    for node, i in position.items():
        values[i, columns["hops_from_victim"]] = float(
            from_victim.get(node, unreachable)
        )

    # Distance to a cash-out point, measured on the reversed graph from every
    # account that pays an exit directly.
    adjacent = set(
        edges.filter(pl.col("dst").is_in(index.exits))["src"].unique().to_list()
    ) & set(position)

    to_exit: dict[str, int] = {node: 0 for node in adjacent}
    frontier = list(adjacent)
    depth = 0
    while frontier and depth < 12:
        depth += 1
        nxt: list[str] = []
        for node in frontier:
            for predecessor in graph.predecessors(node):
                if predecessor not in to_exit:
                    to_exit[predecessor] = depth
                    nxt.append(predecessor)
        frontier = nxt

    for node, i in position.items():
        values[i, columns["hops_to_exit"]] = float(to_exit.get(node, unreachable))


# ---------------------------------------------------------------------------
# account attributes and shared infrastructure
# ---------------------------------------------------------------------------


def _account_features(
    dataset: Dataset,
    order: list[str],
    position: dict[str, int],
    values: np.ndarray,
    columns: dict[str, int],
    edges: pl.DataFrame,
    until: datetime,
) -> None:
    rows = dataset.accounts.filter(pl.col("account_id").is_in(position.keys()))
    as_of = until.date()

    device_of: dict[str, str] = {}
    ip_of: dict[str, str] = {}
    open_of: dict[str, object] = {}

    for row in rows.iter_rows(named=True):
        i = position[row["account_id"]]
        device_of[row["account_id"]] = row["device_fingerprint"]
        ip_of[row["account_id"]] = row["home_ip_prefix"]
        open_of[row["account_id"]] = row["open_date"]

        values[i, columns["account_age_days"]] = float((as_of - row["open_date"]).days)
        # The dormancy break: months of silence, then sudden activity. This is
        # measurable only because the account table records activity from
        # before the simulated window -- see population._prior_activity.
        values[i, columns["dormancy_days"]] = float(
            (as_of - row["prior_activity_date"]).days
        )
        values[i, columns["kyc_video_flag"]] = float(row["kyc_tier"] == "video")
        values[i, columns["kyc_small_flag"]] = float(row["kyc_tier"] == "small")

    _shared_infrastructure(
        dataset, order, position, values, columns, device_of, ip_of, open_of, edges
    )


def _shared_infrastructure(
    dataset: Dataset,
    order: list[str],
    position: dict[str, int],
    values: np.ndarray,
    columns: dict[str, int],
    device_of: dict[str, str],
    ip_of: dict[str, str],
    open_of: dict[str, object],
    edges: pl.DataFrame,
) -> None:
    """The features a per-account rule engine structurally cannot compute.

    Every one of these is a property of an account's *neighbourhood*. This is
    the concrete answer to "isn't this just a classifier on account features" --
    no, because a single account in isolation carries none of this signal.
    """
    # Cluster sizes are counted across the whole population, not just the
    # candidate set: a device shared with accounts outside this incident is
    # still a shared device.
    device_counts = dict(
        dataset.accounts.group_by("device_fingerprint")
        .len()
        .iter_rows()
    )
    ip_counts = dict(
        dataset.accounts.group_by("home_ip_prefix").len().iter_rows()
    )

    for account, i in position.items():
        values[i, columns["device_cluster_size"]] = float(
            device_counts.get(device_of.get(account, ""), 1)
        )
        values[i, columns["ip_cluster_size"]] = float(
            ip_counts.get(ip_of.get(account, ""), 1)
        )

    # Recipient-set overlap. Two accounts paying the same unusual set of
    # counterparties are being operated together, whatever their KYC says.
    recipients: dict[str, set[str]] = {}
    for src, dst in edges.select("src", "dst").iter_rows():
        if src in position:
            recipients.setdefault(src, set()).add(dst)

    payers_of: dict[str, list[str]] = {}
    for account, targets in recipients.items():
        for target in targets:
            payers_of.setdefault(target, []).append(account)

    for account, targets in recipients.items():
        if not targets:
            continue
        best = 0.0
        peers = {
            peer
            for target in targets
            for peer in payers_of.get(target, ())
            if peer != account
        }
        for peer in peers:
            other = recipients.get(peer)
            if not other:
                continue
            union = len(targets | other)
            if union:
                best = max(best, len(targets & other) / union)
        values[position[account], columns["recipient_jaccard_max"]] = best

    # Accounts opened within days of each other by neighbours in the graph --
    # one recruiter walking a group through account opening.
    window = timedelta(days=settings.ring_open_window_days)
    neighbours: dict[str, set[str]] = {}
    for src, dst in edges.select("src", "dst").iter_rows():
        if src in position and dst in position:
            neighbours.setdefault(src, set()).add(dst)
            neighbours.setdefault(dst, set()).add(src)

    for account, i in position.items():
        opened = open_of.get(account)
        if opened is None:
            continue
        close = sum(
            1
            for peer in neighbours.get(account, ())
            if peer in open_of and abs(open_of[peer] - opened) <= window  # type: ignore[operator]
        )
        values[i, columns["same_window_openings"]] = float(close)

    # How many accounts on the same handset turned up in *this* incident.
    #
    # A shared device on its own is weak -- families and cyber cafes share
    # handsets all day. What is not weak is a handset whose other accounts are
    # all standing in the path of the same stolen money. Two ordinary accounts
    # sharing a phone will essentially never co-occur in one incident; eight
    # accounts from one ring always will. This is the single clearest example
    # of a signal that exists only in the neighbourhood.
    incident_by_device: dict[str, int] = {}
    for account in position:
        fingerprint = device_of.get(account)
        if fingerprint:
            incident_by_device[fingerprint] = incident_by_device.get(fingerprint, 0) + 1

    for account, i in position.items():
        fingerprint = device_of.get(account, "")
        values[i, columns["device_peers_in_incident"]] = float(
            max(0, incident_by_device.get(fingerprint, 1) - 1)
        )


# ---------------------------------------------------------------------------
# hard-negative contrast report
# ---------------------------------------------------------------------------

VELOCITY_FEATURES: tuple[str, ...] = (
    "median_residence_minutes",
    "in_out_ratio_1h",
    "turnover_ratio",
    "outflow_within_10min_share",
    "fanout_ratio",
)

SHARED_INFRA_FEATURES: tuple[str, ...] = (
    "device_cluster_size",
    "ip_cluster_size",
    "recipient_jaccard_max",
    "same_window_openings",
    "device_peers_in_incident",
)


def contrast_report(
    matrix: FeatureMatrix, labels: pl.DataFrame, dataset: Dataset | None = None
) -> dict[str, object]:
    """Verify the claim the whole detection story rests on.

    Legitimate high-velocity accounts must look *like mules* on velocity and
    *unlike mules* on shared infrastructure. If that separation is not present,
    the dataset has made the problem too easy and every metric downstream is
    inflated. This returns the comparison rather than asserting it, so the
    numbers can be printed and argued with.
    """
    ds = dataset if dataset is not None else load_dataset()
    frame = matrix.to_frame().join(
        ds.accounts.select("account_id", "archetype"), on="account_id", how="left"
    ).join(
        labels.select("account_id", "is_mule"), on="account_id", how="left"
    ).with_columns(pl.col("is_mule").fill_null(False))

    groups = {
        "mule": frame.filter(pl.col("is_mule")),
        "legit_high_velocity": frame.filter(
            ~pl.col("is_mule") & (pl.col("archetype") == "legit_high_velocity")
        ),
        "other_legitimate": frame.filter(
            ~pl.col("is_mule") & (pl.col("archetype") != "legit_high_velocity")
        ),
    }

    def medians(features: tuple[str, ...]) -> dict[str, dict[str, float]]:
        return {
            name: {
                group: (
                    float(subset[name].median()) if subset.height else float("nan")
                )
                for group, subset in groups.items()
            }
            for name in features
        }

    velocity = medians(VELOCITY_FEATURES)
    shared = medians(SHARED_INFRA_FEATURES)

    def separation(table: dict[str, dict[str, float]]) -> float:
        """Median ratio of mule to hard-negative, across a feature group."""
        ratios = []
        for row in table.values():
            hv = row["legit_high_velocity"]
            mule = row["mule"]
            if math.isfinite(hv) and math.isfinite(mule):
                ratios.append((mule + 1e-6) / (hv + 1e-6))
        return float(np.median(ratios)) if ratios else float("nan")

    return {
        "counts": {group: subset.height for group, subset in groups.items()},
        "velocity": velocity,
        "shared_infrastructure": shared,
        "velocity_separation": separation(velocity),
        "shared_infrastructure_separation": separation(shared),
    }


def format_contrast(report: dict[str, object]) -> str:
    """Render the contrast report as the table the README and CLI both print."""
    lines = [
        "Hard-negative check: legitimate high-velocity accounts vs mules",
        "",
        f"{'feature':<34}{'mule':>14}{'legit hi-vel':>14}{'other legit':>14}",
        "-" * 76,
    ]
    for section, title in (
        ("velocity", "velocity -- hard negatives must look at least as extreme as mules"),
        ("shared_infrastructure", "shared infrastructure -- here they must separate"),
    ):
        lines.append(f"{title}")
        table = report[section]
        assert isinstance(table, dict)
        for name, row in table.items():
            lines.append(
                f"  {name:<32}{row['mule']:>14.3f}"
                f"{row['legit_high_velocity']:>14.3f}"
                f"{row['other_legitimate']:>14.3f}"
            )
        lines.append("")

    velocity_ratio = float(report["velocity_separation"])  # type: ignore[arg-type]
    shared_ratio = float(report["shared_infrastructure_separation"])  # type: ignore[arg-type]

    lines.append(
        f"mule / hard-negative ratio -- velocity: {velocity_ratio:.2f}x, "
        f"shared infrastructure: {shared_ratio:.2f}x"
    )
    lines.append("")
    lines.append(
        "Read this as: on velocity the two groups are not separable in the "
        "direction a rule engine assumes"
        if velocity_ratio < 2.0
        else "WARNING: velocity alone separates mules -- the dataset is too easy"
    )
    lines.append(
        "shared infrastructure does separate them, and that is a neighbourhood "
        "property no per-account rule can compute"
        if shared_ratio > 1.5
        else "WARNING: shared infrastructure does not separate -- the GNN has nothing to learn"
    )
    return "\n".join(lines)
