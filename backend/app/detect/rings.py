"""Ring discovery: Louvain over transfers plus shared infrastructure.

Communities are found on an undirected projection whose edges combine two very
different kinds of evidence:

* **transfer edges**, weighted by log value. Money moving between two accounts
  is evidence they are connected.
* **shared-infrastructure edges**, between accounts on the same device
  fingerprint or IP range, weighted by `shared_infra_edge_weight`.

The second kind is what makes this work. A laundering tree is a *tree* -- cut
any node and the rest falls into separate components, so modularity on transfer
edges alone happily splits one ring into four. Device and IP edges stitch the
branches back together, because the same handset operates accounts across
branches. That is precisely the structure a per-account model cannot represent.

Quality is scored with the adjusted Rand index against the ground-truth ring
assignment, on mule accounts only -- ARI over the whole population would be
dominated by the trivially correct "everyone else is not in a ring" agreement
and would look excellent regardless of whether the rings were recovered.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import networkx as nx
import numpy as np
import polars as pl
from sklearn.metrics import adjusted_rand_score

from app.config import settings
from app.graphstore.build import Dataset, load_dataset

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveredRing:
    """A community the algorithm found, described the way an analyst needs it."""

    ring_id: str
    accounts: tuple[str, ...]
    banks: tuple[str, ...]
    districts: int
    device_clusters: int
    ip_clusters: int
    total_flow_inr: float
    cashout_capacity_inr: float
    mean_p_mule: float
    confidence: float
    dormancy_days_median: float

    @property
    def size(self) -> int:
        return len(self.accounts)


def build_projection(
    accounts: list[str],
    edges: pl.DataFrame,
    dataset: Dataset | None = None,
) -> nx.Graph:
    """Undirected projection: transfers plus shared-infrastructure links."""
    ds = dataset if dataset is not None else load_dataset()
    keep = set(accounts)

    graph = nx.Graph()
    graph.add_nodes_from(accounts)

    internal = edges.filter(pl.col("src").is_in(keep) & pl.col("dst").is_in(keep))
    flows = internal.group_by(["src", "dst"]).agg(pl.col("amount").sum())
    for src, dst, amount in flows.iter_rows():
        if src == dst:
            continue
        # Log value, so one large transfer does not drown out a dense pattern
        # of small ones -- structuring rings are built entirely from the latter.
        weight = math.log1p(float(amount))
        if graph.has_edge(src, dst):
            graph[src][dst]["weight"] += weight
        else:
            graph.add_edge(src, dst, weight=weight)

    _add_shared_infrastructure(graph, ds, keep)
    return graph


def _add_shared_infrastructure(
    graph: nx.Graph, dataset: Dataset, keep: set[str]
) -> None:
    rows = dataset.accounts.filter(pl.col("account_id").is_in(keep))
    weight = settings.shared_infra_edge_weight

    for column in ("device_fingerprint", "home_ip_prefix"):
        grouped = rows.group_by(column).agg(pl.col("account_id"))
        for _, members in grouped.iter_rows():
            # A shared identifier across a huge group is an artefact (a carrier
            # NAT range, a default fingerprint), not a syndicate. Linking those
            # would merge half the graph into one meaningless community.
            if len(members) < 2 or len(members) > settings.max_shared_infra_group:
                continue
            for i, a in enumerate(members):
                for b in members[i + 1 :]:
                    if graph.has_edge(a, b):
                        graph[a][b]["weight"] += weight
                    else:
                        graph.add_edge(a, b, weight=weight)


def detect_rings(
    accounts: list[str],
    edges: pl.DataFrame,
    scores: dict[str, float] | None = None,
    dataset: Dataset | None = None,
) -> tuple[list[DiscoveredRing], dict[str, str]]:
    """Find rings. Returns the summaries and an account -> community mapping."""
    ds = dataset if dataset is not None else load_dataset()
    graph = build_projection(accounts, edges, ds)

    communities = nx.community.louvain_communities(
        graph,
        weight="weight",
        resolution=settings.louvain_resolution,
        seed=settings.master_seed,
    )

    meta = {
        row["account_id"]: row
        for row in ds.accounts.filter(
            pl.col("account_id").is_in(set(accounts))
        ).iter_rows(named=True)
    }
    outflow = dict(
        edges.filter(pl.col("src").is_in(set(accounts)))
        .group_by("src")
        .agg(pl.col("amount").sum())
        .iter_rows()
    )
    exit_flow = dict(
        edges.filter(
            pl.col("src").is_in(set(accounts))
            & pl.col("dst").str.starts_with("EXIT-")
        )
        .group_by("src")
        .agg(pl.col("amount").sum())
        .iter_rows()
    )

    discovered: list[DiscoveredRing] = []
    assignment: dict[str, str] = {}

    ranked = sorted(communities, key=len, reverse=True)
    for position, members in enumerate(ranked):
        if len(members) < settings.min_ring_size:
            continue
        ring_id = f"C{position + 1:02d}"
        ordered = tuple(sorted(members))
        for account in ordered:
            assignment[account] = ring_id

        rows = [meta[a] for a in ordered if a in meta]
        if not rows:
            continue

        p_mule = [scores.get(a, 0.0) for a in ordered] if scores else [0.0]
        dormancy = [
            (r["open_date"] - r["prior_activity_date"]).days for r in rows
        ]

        discovered.append(
            DiscoveredRing(
                ring_id=ring_id,
                accounts=ordered,
                banks=tuple(sorted({str(r["bank_id"]) for r in rows})),
                districts=len({str(r["district"]) for r in rows}),
                device_clusters=len({str(r["device_fingerprint"]) for r in rows}),
                ip_clusters=len({str(r["home_ip_prefix"]) for r in rows}),
                total_flow_inr=round(
                    sum(outflow.get(a, 0.0) for a in ordered), 2
                ),
                cashout_capacity_inr=round(
                    sum(exit_flow.get(a, 0.0) for a in ordered), 2
                ),
                mean_p_mule=round(float(np.mean(p_mule)), 4),
                confidence=_confidence(ordered, rows, scores),
                dormancy_days_median=float(np.median(dormancy)) if dormancy else 0.0,
            )
        )

    return discovered, assignment


def _confidence(
    accounts: tuple[str, ...],
    rows: list[dict[str, object]],
    scores: dict[str, float] | None,
) -> float:
    """How much this community looks like an organisation rather than a crowd.

    Three ingredients, none sufficient alone: the detector's average suspicion,
    how concentrated the group is on shared devices, and how tightly its
    accounts were opened together.
    """
    suspicion = (
        float(np.mean([scores.get(a, 0.0) for a in accounts])) if scores else 0.0
    )

    devices = len({str(r["device_fingerprint"]) for r in rows})
    concentration = 1.0 - devices / max(len(rows), 1)

    opens = sorted(r["open_date"] for r in rows)  # type: ignore[type-var]
    spread_days = (opens[-1] - opens[0]).days if len(opens) > 1 else 0  # type: ignore[operator]
    tightness = 1.0 / (1.0 + spread_days / max(settings.ring_open_window_days, 1))

    return round(
        float(np.clip(0.5 * suspicion + 0.3 * concentration + 0.2 * tightness, 0, 1)),
        3,
    )


def ring_ari(
    assignment: dict[str, str], dataset: Dataset | None = None
) -> dict[str, float]:
    """Adjusted Rand index of discovered rings against ground truth.

    Scored over mule accounts only. Including the whole population would let
    the trivial agreement on "not in any ring" dominate and report a high score
    for a clustering that recovered nothing.
    """
    ds = dataset if dataset is not None else load_dataset()
    truth = {
        row["account_id"]: row["ring_id"]
        for row in ds.labels.filter(pl.col("is_mule")).iter_rows(named=True)
    }

    shared = [a for a in assignment if a in truth]
    if len(shared) < 2:
        return {"ari": float("nan"), "n_accounts": len(shared), "n_communities": 0}

    predicted = [assignment[a] for a in shared]
    actual = [truth[a] for a in shared]

    covered = len(shared) / max(len(truth), 1)
    return {
        "ari": float(adjusted_rand_score(actual, predicted)),
        "n_accounts": len(shared),
        "n_communities": len(set(predicted)),
        "n_true_rings": len(set(actual)),
        "mule_coverage": round(covered, 4),
    }
