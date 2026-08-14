"""Fund tracing: following the victim's money through the graph.

This module answers one question -- *where is the stolen money right now?* --
using only what a bank could actually see: transactions that have already
happened. It never reads the `is_fraud` label. If it did, every number
downstream would be circular and the benchmark would be theatre.

**The tracing rule (pro-rata pooling).** Money is fungible, so once ₹2L of
stolen funds lands in an account that also holds ₹8L of its own, no rupee
leaving that account is identifiably stolen. The pooling method used in AML
fund tracing says: taint the outflow in proportion to the tainted share of the
inflow. An account whose window inflow was 20% stolen sends out money that is
20% stolen.

That proportionality is what makes the innocence budget mean something. A naive
tracer marks every downstream account fully guilty and the freeze list explodes;
this one lets taint decay through legitimate accounts, so the solver has to
decide whether a 6%-tainted salary account is worth freezing.

Traversal is event-driven over a prebuilt index, so a trace costs time
proportional to the accounts the money actually reaches, not to the size of the
dataset.
"""

from __future__ import annotations

import heapq
import logging
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

import numpy as np
import polars as pl

from app.config import settings
from app.graphstore.build import Dataset, load_dataset
from app.simulator.population import EPOCH_REF

log = logging.getLogger(__name__)


def to_epoch(when: datetime) -> int:
    """Seconds since the epoch, timezone-free and machine-independent."""
    return int((when - EPOCH_REF).total_seconds())


# ---------------------------------------------------------------------------
# transaction index
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutEdges:
    """Every transfer leaving one account, in time order."""

    time: np.ndarray  # int64 epoch seconds
    dst: tuple[str, ...]
    amount: np.ndarray  # float64
    channel: tuple[str, ...]


@dataclass(frozen=True)
class TransactionIndex:
    """Adjacency and cumulative-inflow structures over the whole dataset.

    Built once and cached. Every trace and every replay reads from this, which
    is the difference between a benchmark that runs in a minute and one that
    runs in an hour.
    """

    out: dict[str, OutEdges]
    in_time: dict[str, np.ndarray]
    in_cumulative: dict[str, np.ndarray]
    exits: frozenset[str]
    exit_kind: dict[str, str]

    def inflow_between(self, account: str, start: int, end: int) -> float:
        """Total value received by `account` in [start, end]. All of it, not just taint."""
        times = self.in_time.get(account)
        if times is None or times.size == 0:
            return 0.0
        cumulative = self.in_cumulative[account]
        lo = int(np.searchsorted(times, start, side="left"))
        hi = int(np.searchsorted(times, end, side="right"))
        if hi <= lo:
            return 0.0
        before = cumulative[lo - 1] if lo > 0 else 0.0
        return float(cumulative[hi - 1] - before)


@lru_cache(maxsize=1)
def transaction_index(dataset: Dataset | None = None) -> TransactionIndex:
    ds = dataset if dataset is not None else load_dataset()
    txns = ds.transactions.with_columns(
        pl.col("timestamp").dt.epoch(time_unit="s").alias("epoch")
    )

    outgoing: dict[str, OutEdges] = {}
    grouped = txns.sort("epoch").group_by("src").agg(
        pl.col("epoch"), pl.col("dst"), pl.col("amount"), pl.col("channel")
    )
    for row in grouped.iter_rows(named=True):
        outgoing[row["src"]] = OutEdges(
            time=np.asarray(row["epoch"], dtype=np.int64),
            dst=tuple(row["dst"]),
            amount=np.asarray(row["amount"], dtype=np.float64),
            channel=tuple(row["channel"]),
        )

    in_time: dict[str, np.ndarray] = {}
    in_cumulative: dict[str, np.ndarray] = {}
    incoming = txns.sort("epoch").group_by("dst").agg(pl.col("epoch"), pl.col("amount"))
    for row in incoming.iter_rows(named=True):
        in_time[row["dst"]] = np.asarray(row["epoch"], dtype=np.int64)
        in_cumulative[row["dst"]] = np.cumsum(
            np.asarray(row["amount"], dtype=np.float64)
        )

    exit_rows = ds.accounts.filter(pl.col("exit_kind") != "")
    exit_kind = dict(
        zip(exit_rows["account_id"].to_list(), exit_rows["exit_kind"].to_list())
    )

    log.info("indexed %d sending accounts", len(outgoing))
    return TransactionIndex(
        out=outgoing,
        in_time=in_time,
        in_cumulative=in_cumulative,
        exits=frozenset(exit_kind),
        exit_kind=exit_kind,
    )


# ---------------------------------------------------------------------------
# taint state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaintFlow:
    """One observed transfer, and how much of it was the victim's money."""

    src: str
    dst: str
    amount: float
    tainted: float
    epoch: int
    channel: str


@dataclass
class TaintState:
    """Where the stolen money is, as of `until`."""

    victim: str
    amount_inr: float
    t0: int
    until: int

    #: Tainted rupees sitting in each account right now -- the freezable pool.
    held: dict[str, float] = field(default_factory=dict)
    #: Tainted rupees that have ever passed through each account.
    through: dict[str, float] = field(default_factory=dict)
    #: When taint first reached each account.
    first_seen: dict[str, int] = field(default_factory=dict)
    #: Tainted rupees that have already left the banking system.
    exited: float = 0.0
    #: Per exit node, how much left through it.
    exited_by_node: dict[str, float] = field(default_factory=dict)
    flows: list[TaintFlow] = field(default_factory=list)

    @property
    def still_inside(self) -> float:
        return sum(self.held.values())

    @property
    def touched(self) -> list[str]:
        return sorted(self.through)

    def minute_of(self, epoch: int) -> int:
        return int((epoch - self.t0) // 60)


def trace_taint(
    victim: str,
    amount_inr: float,
    t0: datetime,
    until: datetime,
    index: TransactionIndex | None = None,
) -> TaintState:
    """Follow `amount_inr` from `victim` at `t0` forward, up to `until`.

    Returns the tainted balance held by every account at `until`, which is the
    state the interdiction solver plans against.
    """
    idx = index if index is not None else transaction_index()
    start, end = to_epoch(t0), to_epoch(until)

    state = TaintState(victim=victim, amount_inr=amount_inr, t0=start, until=end)
    state.held[victim] = amount_inr
    state.through[victim] = amount_inr
    state.first_seen[victim] = start

    # A single event loop in global time order, not a walk per account. An
    # account can be credited several times -- structuring rings collect a
    # dozen sub-threshold chunks before forwarding -- so its outgoing edges
    # must each be evaluated against the taint it holds *at that moment*.
    # Expanding one account to exhaustion on first arrival would forward the
    # first chunk and silently lose the rest.
    queue: list[tuple[int, str, int]] = []
    entered: set[str] = {victim}
    _arm(queue, idx, victim, start, end)

    while queue:
        when, account, cursor = heapq.heappop(queue)
        edges = idx.out[account]
        _arm_next(queue, edges, account, cursor + 1, end)

        available = state.held.get(account, 0.0)
        if available <= settings.taint_floor_inr:
            continue

        share = _taint_share(state, idx, account, when, available)
        if share < settings.taint_min_share:
            continue

        moved = min(available, float(edges.amount[cursor]) * share)
        if moved <= settings.taint_floor_inr:
            continue

        dst = edges.dst[cursor]
        state.held[account] = available - moved
        state.flows.append(
            TaintFlow(
                src=account,
                dst=dst,
                amount=float(edges.amount[cursor]),
                tainted=moved,
                epoch=when,
                channel=edges.channel[cursor],
            )
        )

        if dst in idx.exits:
            state.exited += moved
            state.exited_by_node[dst] = state.exited_by_node.get(dst, 0.0) + moved
            continue

        state.held[dst] = state.held.get(dst, 0.0) + moved
        state.through[dst] = state.through.get(dst, 0.0) + moved
        state.first_seen.setdefault(dst, when)
        if dst not in entered:
            entered.add(dst)
            _arm(queue, idx, dst, when, end)

    return state


def _arm(
    queue: list[tuple[int, str, int]],
    index: TransactionIndex,
    account: str,
    since: int,
    end: int,
) -> None:
    """Queue an account's first outgoing transfer at or after `since`."""
    edges = index.out.get(account)
    if edges is None:
        return
    cursor = int(np.searchsorted(edges.time, since, side="left"))
    _arm_next(queue, edges, account, cursor, end)


def _arm_next(
    queue: list[tuple[int, str, int]],
    edges: OutEdges,
    account: str,
    cursor: int,
    end: int,
) -> None:
    if cursor >= len(edges.dst):
        return
    when = int(edges.time[cursor])
    if when > end:
        return
    heapq.heappush(queue, (when, account, cursor))


def _taint_share(
    state: TaintState,
    index: TransactionIndex,
    account: str,
    when: int,
    available: float,
) -> float:
    """Fraction of this account's outflow that is the victim's money.

    Pro-rata pooling: tainted inflow over total inflow across the incident
    window. An account that received nothing but stolen funds forwards them
    whole; one that also received a salary forwards a diluted share.
    """
    total_in = index.inflow_between(account, state.t0, when)
    tainted_in = state.through.get(account, 0.0)
    if account == state.victim:
        # The victim's own money is the source, not an inflow.
        total_in = max(total_in, 0.0) + state.amount_inr
    denominator = max(total_in, tainted_in, available)
    if denominator <= 0.0:
        return 0.0
    return min(1.0, tainted_in / denominator)


# ---------------------------------------------------------------------------
# candidate frontier
# ---------------------------------------------------------------------------


def candidate_accounts(
    state: TaintState,
    hops: int | None = None,
    index: TransactionIndex | None = None,
    limit: int | None = None,
) -> list[str]:
    """Accounts the money could plausibly reach next, and so worth scoring.

    This is the set the detector scores and the solver may freeze: the accounts
    taint has already touched, plus everything within `hops` of them along
    *historically observed* edges. That expansion is the whole reason a freeze
    can get ahead of the money -- a ring reuses its accounts, so where it sent
    money last week is where it will send money in ten minutes.

    Two rules keep this honest:

    * Only edges at or before the complaint time count. Expanding along edges
      that have not happened yet would hand the solver the answer sheet.
    * The set is deliberately *not* pre-narrowed to suspicious accounts. It
      includes every ordinary counterparty in reach, so the solver has to earn
      its precision instead of being given it.

    Exit nodes are excluded -- an ATM is not an account anyone can freeze.
    """
    idx = index if index is not None else transaction_index()
    cap = limit if limit is not None else settings.incident_max_nodes
    depth = hops if hops is not None else settings.candidate_hops

    frontier = set(state.through) - idx.exits
    seen = set(frontier)

    for _ in range(depth):
        if len(seen) >= cap:
            break
        nxt: set[str] = set()
        for account in frontier:
            edges = idx.out.get(account)
            if edges is None:
                continue
            horizon = int(np.searchsorted(edges.time, state.until, side="right"))
            for i in range(horizon):
                dst = edges.dst[i]
                if dst not in seen and dst not in idx.exits:
                    nxt.add(dst)
        # Sorted before truncation so the candidate set is reproducible.
        room = cap - len(seen)
        additions = sorted(nxt)[:room]
        seen.update(additions)
        frontier = set(additions)

    return sorted(seen)
