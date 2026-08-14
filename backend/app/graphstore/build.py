"""Dataset loading and incident subgraph construction.

The whole dataset is small enough (a few hundred thousand rows) to hold in
memory, so it is loaded once and cached. Requests then slice an *incident
subgraph* out of it: the set of accounts money can actually reach from the
victim, within the response horizon.

Reachability here is **temporal**, not topological. An edge u->v at time t is
only usable if the money arrived at u before t. Ignoring that would pull in
accounts that transacted with a mule hours *before* the fraud and label them
part of the incident, which is both wrong and the kind of error that produces
impressively large, meaningless graphs.
"""

from __future__ import annotations

import heapq
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache

import polars as pl

from app.config import settings
from app.simulator.population import EPOCH_REF
from app.simulator.scenarios import SCENARIOS_BY_ID, Scenario

log = logging.getLogger(__name__)


class DatasetMissingError(RuntimeError):
    """Raised when the parquet artifacts have not been generated yet."""


# eq=False so the dataclass hashes by identity. The default would try to hash
# the DataFrames themselves, which fails, and lru_cache needs Dataset hashable.
@dataclass(frozen=True, eq=False)
class Dataset:
    accounts: pl.DataFrame
    transactions: pl.DataFrame
    labels: pl.DataFrame
    episodes: pl.DataFrame

    @property
    def account_index(self) -> dict[str, dict[str, object]]:
        return _account_index(self)

    @property
    def mule_ids(self) -> frozenset[str]:
        return _mule_ids(self)


@lru_cache(maxsize=1)
def load_dataset() -> Dataset:
    """Load the generated parquet artifacts. Cached for the process lifetime."""
    missing = [
        p.name
        for p in (
            settings.accounts_path,
            settings.transactions_path,
            settings.labels_path,
            settings.episodes_path,
        )
        if not p.exists()
    ]
    if missing:
        raise DatasetMissingError(
            f"Missing {', '.join(missing)}. Run: python -m app.simulator.generator"
        )

    dataset = Dataset(
        accounts=pl.read_parquet(settings.accounts_path),
        transactions=pl.read_parquet(settings.transactions_path),
        labels=pl.read_parquet(settings.labels_path),
        episodes=pl.read_parquet(settings.episodes_path),
    )
    log.info(
        "loaded %d accounts / %d transactions",
        dataset.accounts.height,
        dataset.transactions.height,
    )
    return dataset


@lru_cache(maxsize=1)
def _account_index(dataset: Dataset) -> dict[str, dict[str, object]]:
    joined = dataset.accounts.join(dataset.labels, on="account_id", how="left")
    return {row["account_id"]: row for row in joined.iter_rows(named=True)}


@lru_cache(maxsize=1)
def _mule_ids(dataset: Dataset) -> frozenset[str]:
    """Ground truth. Used to *score* results, never to produce them."""
    return frozenset(
        dataset.labels.filter(pl.col("is_mule"))["account_id"].to_list()
    )


# ---------------------------------------------------------------------------
# incident subgraph
# ---------------------------------------------------------------------------


@dataclass
class GraphNode:
    account_id: str
    kind: str  # victim | mule | legit | exit
    bank_id: str
    district: str
    archetype: str
    is_mule: bool
    ring_id: str
    layer_index: int
    is_cashout_node: bool
    exit_kind: str
    depth: int  # hops from the victim along the money's path
    first_seen_minute: int  # minutes after the incident
    amount_in: float
    amount_out: float
    #: The victim's money that passed through this account.
    tainted_in: float


@dataclass
class GraphLink:
    source: str
    target: str
    amount: float
    #: How much of this transfer was the victim's money. Zero for ordinary
    #: traffic that merely happens to touch an account in the incident.
    tainted: float
    minute: int
    channel: str
    is_fraud: bool


@dataclass
class IncidentGraph:
    scenario_id: str
    victim_account: str
    incident_time: datetime
    horizon_minutes: int
    nodes: list[GraphNode] = field(default_factory=list)
    links: list[GraphLink] = field(default_factory=list)
    truncated: bool = False

    @property
    def total_laundered(self) -> float:
        """Value of this victim's money moving, counted once per hop."""
        return sum(link.tainted for link in self.links)


def _window(dataset: Dataset, start: datetime, end: datetime) -> pl.DataFrame:
    return dataset.transactions.filter(
        (pl.col("timestamp") >= start) & (pl.col("timestamp") <= end)
    )


def build_incident_graph(
    scenario_id: str,
    context_hops: int | None = None,
    *,
    victim_account: str | None = None,
    amount_inr: float | None = None,
    incident_time: datetime | None = None,
) -> IncidentGraph:
    """Slice the incident subgraph for a scenario out of the full dataset.

    The graph is built from the **traced money**, not from every fraudulent
    transfer in the window. Those are very different sets: the ring runs a
    laundering episode every day or two, so a six-hour window around one
    incident routinely contains other victims' money moving through the same
    accounts. Drawing all of it produced a canvas full of long edges that had
    nothing to do with the complaint on screen.

    Tracing here uses the full horizon rather than stopping at the complaint,
    because the canvas is a replay of what happened -- the *solver* is the part
    that is restricted to what was visible at the complaint time.
    """
    # The three overrides let a complaint filed through intake draw its canvas
    # from the same code as a seeded scenario. They are passed explicitly
    # rather than as an `Incident` because `incidents.py` imports from this
    # module, and taking the type here would close the cycle.
    if victim_account is None or amount_inr is None or incident_time is None:
        scenario = SCENARIOS_BY_ID.get(scenario_id)
        if scenario is None:
            raise KeyError(f"Unknown scenario {scenario_id!r}")
        victim_account = scenario.victim_account
        amount_inr = scenario.amount_inr
        incident_time = scenario.incident_time

    from app.graphstore.trace import trace_taint, transaction_index

    dataset = load_dataset()
    horizon = timedelta(hours=settings.incident_horizon_hours)
    start = incident_time
    end = start + horizon

    state = trace_taint(
        victim_account,
        amount_inr,
        start,
        end,
        transaction_index(),
    )

    window = _window(dataset, start, end)
    arrival = {
        account: start + timedelta(seconds=epoch - state.t0)
        for account, epoch in state.first_seen.items()
    }
    depth = _taint_depth(state, victim_account)

    core = set(arrival)
    if context_hops is None:
        context_hops = settings.incident_context_hops
    context = _context_neighbours(window, core) if context_hops > 0 else set()

    keep = core | context
    edges = window.filter(pl.col("src").is_in(keep) & pl.col("dst").is_in(keep))
    tainted = {
        (flow.src, flow.dst, flow.epoch): flow.tainted for flow in state.flows
    }

    return _assemble(
        dataset, scenario_id, victim_account, arrival, depth, context, edges,
        start, state, tainted,
    )


def _taint_depth(state, victim: str) -> dict[str, int]:
    """Hops from the victim along the path the money actually took."""
    children: dict[str, list[str]] = {}
    for flow in sorted(state.flows, key=lambda f: f.epoch):
        children.setdefault(flow.src, []).append(flow.dst)

    depth = {victim: 0}
    frontier = [victim]
    while frontier:
        nxt: list[str] = []
        for node in frontier:
            for child in children.get(node, ()):
                if child not in depth:
                    depth[child] = depth[node] + 1
                    nxt.append(child)
        frontier = nxt
    return depth


def _temporal_reach(
    window: pl.DataFrame, victim: str, t0: datetime
) -> tuple[dict[str, datetime], dict[str, int]]:
    """Earliest time money could arrive at each account, and hop depth.

    A Dijkstra-style sweep over time: pop the account the money reaches
    soonest, then relax only the edges leaving it *after* that moment.
    """
    outgoing: dict[str, list[tuple[datetime, str]]] = {}
    for row in window.select(["src", "dst", "timestamp"]).iter_rows():
        outgoing.setdefault(row[0], []).append((row[2], row[1]))
    for edges in outgoing.values():
        edges.sort()

    arrival: dict[str, datetime] = {victim: t0}
    depth: dict[str, int] = {victim: 0}
    queue: list[tuple[datetime, int, str]] = [(t0, 0, victim)]

    while queue and len(arrival) < settings.incident_max_nodes:
        at, hops, node = heapq.heappop(queue)
        if at > arrival.get(node, at):
            continue

        for when, nxt in outgoing.get(node, ()):
            if when < at:
                continue  # money was not there yet
            if nxt in arrival and arrival[nxt] <= when:
                continue
            arrival[nxt] = when
            depth[nxt] = hops + 1
            heapq.heappush(queue, (when, hops + 1, nxt))

    return arrival, depth


def _context_neighbours(window: pl.DataFrame, core: set[str]) -> set[str]:
    """One hop of ordinary neighbours, for false-positive realism.

    Without these the graph contains nothing but accounts downstream of fraud,
    so every model scores perfectly and the metrics mean nothing.
    """
    touching = window.filter(pl.col("src").is_in(core) | pl.col("dst").is_in(core))
    neighbours = set(touching["src"].to_list()) | set(touching["dst"].to_list())
    extra = neighbours - core

    budget = max(0, settings.incident_max_nodes - len(core))
    if len(extra) <= budget:
        return extra
    return set(sorted(extra)[:budget])


def _assemble(
    dataset: Dataset,
    scenario_id: str,
    victim_account: str,
    arrival: dict[str, datetime],
    depth: dict[str, int],
    context: set[str],
    edges: pl.DataFrame,
    t0: datetime,
    state: object,
    tainted: dict[tuple[str, str, int], float],
) -> IncidentGraph:
    index = dataset.account_index

    flow_in: dict[str, float] = {}
    flow_out: dict[str, float] = {}
    links: list[GraphLink] = []

    for row in edges.iter_rows(named=True):
        minute = int((row["timestamp"] - t0).total_seconds() // 60)
        # Keyed on (src, dst, epoch) to match the traced flows exactly. Note
        # `datetime.timestamp()` is never used -- it reads the machine's local
        # timezone and would make this depend on where the code runs.
        key = (
            row["src"],
            row["dst"],
            int((row["timestamp"] - EPOCH_REF).total_seconds()),
        )
        links.append(
            GraphLink(
                source=row["src"],
                target=row["dst"],
                amount=float(row["amount"]),
                tainted=round(tainted.get(key, 0.0), 2),
                minute=minute,
                channel=row["channel"],
                is_fraud=bool(row["is_fraud"]),
            )
        )
        flow_out[row["src"]] = flow_out.get(row["src"], 0.0) + float(row["amount"])
        flow_in[row["dst"]] = flow_in.get(row["dst"], 0.0) + float(row["amount"])

    nodes: list[GraphNode] = []
    for account_id in sorted(set(arrival) | context):
        meta = index.get(account_id)
        if meta is None:
            continue

        archetype = str(meta["archetype"])
        is_mule = bool(meta["is_mule"]) if meta["is_mule"] is not None else False

        if account_id == victim_account:
            kind = "victim"
        elif archetype == "exit_point":
            kind = "exit"
        elif is_mule:
            kind = "mule"
        else:
            kind = "legit"

        seen = arrival.get(account_id)
        nodes.append(
            GraphNode(
                account_id=account_id,
                kind=kind,
                bank_id=str(meta["bank_id"]),
                district=str(meta["district"]),
                archetype=archetype,
                is_mule=is_mule,
                ring_id=str(meta["ring_id"] or ""),
                layer_index=int(meta["layer_index"]) if meta["layer_index"] is not None else -1,
                is_cashout_node=bool(meta["is_cashout_node"])
                if meta["is_cashout_node"] is not None
                else False,
                exit_kind=str(meta["exit_kind"] or ""),
                depth=depth.get(account_id, -1),
                first_seen_minute=int((seen - t0).total_seconds() // 60) if seen else -1,
                amount_in=round(flow_in.get(account_id, 0.0), 2),
                amount_out=round(flow_out.get(account_id, 0.0), 2),
                tainted_in=round(
                    getattr(state, "through", {}).get(account_id, 0.0), 2
                ),
            )
        )

    return IncidentGraph(
        scenario_id=scenario_id,
        victim_account=victim_account,
        # `t0` is the incident time -- the same value the caller sliced the
        # window from, so the graph cannot report a different start than it
        # was built against.
        incident_time=t0,
        horizon_minutes=settings.incident_horizon_hours * 60,
        nodes=nodes,
        links=links,
        truncated=len(arrival) >= settings.incident_max_nodes,
    )


# ---------------------------------------------------------------------------
# summaries
# ---------------------------------------------------------------------------


def dataset_summary() -> dict[str, object]:
    """Headline statistics for the dataset overview panel.

    Runs as SQL against the DuckDB warehouse. This is the division of labour
    the project commits to: polars holds the hot path, where an incident is
    sliced and scored inside a request, and DuckDB answers anything that scans
    the whole dataset to produce a rollup. Doing full-table aggregates in
    Python loops is what an embedded analytical database exists to avoid.
    """
    from app.graphstore import warehouse

    try:
        headline = warehouse.query(
            """
            SELECT
              (SELECT count(*) FROM retail_accounts)                       AS accounts,
              (SELECT count(*) FROM account_facts
                 WHERE archetype = 'exit_point')                           AS exit_nodes,
              (SELECT count(*) FROM transactions)                          AS transactions,
              (SELECT count(*) FROM transactions WHERE is_fraud)           AS fraud_transactions,
              (SELECT count(*) FROM retail_accounts WHERE is_mule)         AS mule_accounts,
              (SELECT count(DISTINCT bank_id) FROM retail_accounts)        AS banks,
              (SELECT count(DISTINCT district) FROM retail_accounts)       AS districts,
              (SELECT coalesce(sum(amount), 0) FROM transactions
                 WHERE is_fraud)                                           AS total_laundered_inr
            """
        )[0]
        archetypes = warehouse.query(
            "SELECT archetype AS name, count(*) AS count FROM retail_accounts "
            "GROUP BY archetype ORDER BY count DESC"
        )
        channels = warehouse.query(
            "SELECT channel AS name, count(*) AS count FROM transactions "
            "GROUP BY channel ORDER BY count DESC"
        )
        hourly = warehouse.query(
            "SELECT hour(timestamp) AS hour, count(*) AS count FROM transactions "
            "GROUP BY 1 ORDER BY 1"
        )
    except warehouse.WarehouseMissingError as exc:
        raise DatasetMissingError(str(exc)) from exc

    accounts = int(headline["accounts"])
    return {
        "accounts": accounts,
        "exit_nodes": int(headline["exit_nodes"]),
        "transactions": int(headline["transactions"]),
        "fraud_transactions": int(headline["fraud_transactions"]),
        "mule_accounts": int(headline["mule_accounts"]),
        "mule_prevalence": round(int(headline["mule_accounts"]) / max(accounts, 1), 5),
        "banks": int(headline["banks"]),
        "districts": int(headline["districts"]),
        "total_laundered_inr": round(float(headline["total_laundered_inr"]), 2),
        "archetypes": [
            {"name": r["name"], "count": int(r["count"])} for r in archetypes
        ],
        "channels": [{"name": r["name"], "count": int(r["count"])} for r in channels],
        "hourly": [
            {"hour": int(r["hour"]), "count": int(r["count"])} for r in hourly
        ],
    }


def ring_summaries() -> list[dict[str, object]]:
    """Ground-truth per-ring rollup: who they are, what they touch, how much moved.

    Also a SQL rollup over the whole dataset, for the same reason as above.
    These are the generator's labels, shown so the *discovered* rings in
    `/api/rings/{scenario_id}` can be checked rather than taken on trust.
    """
    from app.graphstore import warehouse

    try:
        rows = warehouse.query(
            """
            WITH members AS (
              SELECT ring_id,
                     any_value(typology)                  AS typology,
                     count(*)                             AS accounts,
                     count(DISTINCT bank_id)              AS bank_count,
                     count(DISTINCT district)             AS districts,
                     count(DISTINCT device_fingerprint)   AS device_clusters,
                     max(layer_index)                     AS max_layer,
                     count(*) FILTER (WHERE is_cashout_node) AS cashout_nodes,
                     -- Median days of silence before the incident window. The
                     -- rented-account tell, as a number per ring.
                     median(date_diff('day', prior_activity_date, ?::DATE))
                                                          AS dormancy_days
              FROM retail_accounts
              WHERE is_mule
              GROUP BY ring_id
            ),
            flows AS (
              SELECT ring_id, sum(amount) AS total_flow, count(*) AS txn_count
              FROM transactions WHERE is_fraud GROUP BY ring_id
            )
            SELECT m.*,
                   coalesce(f.total_flow, 0) AS total_flow_inr,
                   coalesce(f.txn_count, 0)  AS txn_count
            FROM members m LEFT JOIN flows f USING (ring_id)
            ORDER BY m.ring_id
            """,
            [settings.sim_end_date],
        )
        banks = warehouse.query(
            "SELECT ring_id, bank_id FROM retail_accounts WHERE is_mule "
            "GROUP BY ring_id, bank_id ORDER BY ring_id, bank_id"
        )
    except warehouse.WarehouseMissingError as exc:
        raise DatasetMissingError(str(exc)) from exc

    banks_by_ring: dict[str, list[str]] = {}
    for row in banks:
        banks_by_ring.setdefault(str(row["ring_id"]), []).append(str(row["bank_id"]))

    return [
        {
            "ring_id": str(row["ring_id"]),
            "typology": str(row["typology"]),
            "accounts": int(row["accounts"]),
            "banks": banks_by_ring.get(str(row["ring_id"]), []),
            "districts": int(row["districts"]),
            "device_clusters": int(row["device_clusters"]),
            "max_layer": int(row["max_layer"]),
            "cashout_nodes": int(row["cashout_nodes"]),
            "total_flow_inr": round(float(row["total_flow_inr"]), 2),
            "txn_count": int(row["txn_count"]),
            "dormancy_days": int(row["dormancy_days"] or 0),
        }
        for row in rows
    ]