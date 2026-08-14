"""Train every detection tier and print the comparison table.

    python -m app.detect.train

Produces `models/gbdt.txt`, `models/detector.json`, optionally `models/gnn.pt`,
and `data/detector_report.json`, which the Evaluation tab renders directly.

The comparison is the deliverable, not the model. Three tiers are trained on
identical data and scored on identical held-out incidents, so the table answers
"what does the graph buy you over a rule engine" with a number instead of a
claim. Rings 01, 05, 09 and 12 -- one per typology, including the stage demo's
ring -- never appear in training at all.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import numpy as np
import polars as pl
from sklearn.metrics import average_precision_score, precision_score, recall_score

from app.config import settings
from app.detect import baseline_rules, gnn
from app.detect.gbdt import Detector, train_detector
from app.detect.rings import detect_rings, ring_ari
from app.graphstore.build import Dataset, load_dataset
from app.graphstore.features import (
    FeatureMatrix,
    build_features,
    contrast_report,
    format_contrast,
)
from app.graphstore.incidents import Incident, episodes_for
from app.graphstore.trace import (
    TransactionIndex,
    candidate_accounts,
    trace_taint,
    transaction_index,
)

log = logging.getLogger(__name__)


@dataclass
class IncidentSample:
    """One incident's candidate accounts, features and ground truth."""

    incident: Incident
    matrix: FeatureMatrix
    labels: np.ndarray
    layer_index: np.ndarray


def build_samples(
    incidents: list[Incident],
    dataset: Dataset | None = None,
    index: TransactionIndex | None = None,
    limit: int | None = None,
) -> list[IncidentSample]:
    """Trace, expand and featurise a list of incidents."""
    ds = dataset if dataset is not None else load_dataset()
    idx = index if index is not None else transaction_index()

    truth = {
        row["account_id"]: (bool(row["is_mule"]), int(row["layer_index"]))
        for row in ds.labels.iter_rows(named=True)
    }

    samples: list[IncidentSample] = []
    for position, incident in enumerate(incidents):
        if limit is not None and position >= limit:
            break

        state = trace_taint(
            incident.victim_account,
            incident.amount_inr,
            incident.incident_time,
            incident.complaint_time,
            idx,
        )
        candidates = candidate_accounts(state, index=idx)
        if len(candidates) < 8:
            continue

        matrix = build_features(
            candidates, incident.victim_account, incident.complaint_time, ds, idx
        )
        labels = np.array(
            [truth.get(a, (False, -1))[0] for a in candidates], dtype=np.float64
        )
        layers = np.array(
            [truth.get(a, (False, -1))[1] for a in candidates], dtype=np.int64
        )
        samples.append(
            IncidentSample(
                incident=incident, matrix=matrix, labels=labels, layer_index=layers
            )
        )

        if position % 25 == 0:
            log.info(
                "featurised %d/%d incidents (latest: %d candidates)",
                position + 1,
                len(incidents),
                len(candidates),
            )

    return samples


def stack(samples: list[IncidentSample]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flatten samples into (features, labels, incident group ids)."""
    features = np.vstack([s.matrix.values for s in samples]).astype(np.float64)
    labels = np.concatenate([s.labels for s in samples])
    groups = np.concatenate(
        [
            np.full(len(s.labels), fill_value=i, dtype=np.int64)
            for i, s in enumerate(samples)
        ]
    )
    return features, labels, groups


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------


def precision_at_k(labels: np.ndarray, scores: np.ndarray, k: int) -> float:
    """Of the k most suspicious accounts, what share are actually mules.

    This is the metric that matches how the system is used. Nobody freezes an
    ROC curve; an operations team works down a ranked list until its authority
    runs out.
    """
    if len(scores) == 0:
        return float("nan")
    k = min(k, len(scores))
    top = np.argsort(-scores)[:k]
    return float(labels[top].sum() / k)


def evaluate_tier(
    name: str, samples: list[IncidentSample], scores: list[np.ndarray]
) -> dict[str, object]:
    labels = np.concatenate([s.labels for s in samples])
    flat = np.concatenate(scores)

    binary = (flat >= 0.5).astype(np.float64)
    return {
        "tier": name,
        "auc_pr": float(average_precision_score(labels, flat)),
        "precision_at_100": precision_at_k(labels, flat, 100),
        "precision_at_50": precision_at_k(labels, flat, 50),
        "precision": float(precision_score(labels, binary, zero_division=0)),
        "recall": float(recall_score(labels, binary, zero_division=0)),
        "flagged": int(binary.sum()),
        "positives": int(labels.sum()),
        "rows": int(len(labels)),
    }


def format_table(rows: list[dict[str, object]]) -> str:
    header = (
        f"{'tier':<22}{'AUC-PR':>9}{'P@100':>9}{'P@50':>9}"
        f"{'precision':>11}{'recall':>9}{'flagged':>9}"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{str(row['tier']):<22}{float(row['auc_pr']):>9.3f}"
            f"{float(row['precision_at_100']):>9.3f}"
            f"{float(row['precision_at_50']):>9.3f}"
            f"{float(row['precision']):>11.3f}"
            f"{float(row['recall']):>9.3f}"
            f"{int(row['flagged']):>9d}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GNN encoding
# ---------------------------------------------------------------------------


def encode_sample(
    sample: IncidentSample, dataset: Dataset, until_epoch: int
) -> gnn.GraphSample:
    """Turn one incident into the node/edge tensors the GNN consumes."""
    order = {account: i for i, account in enumerate(sample.matrix.account_ids)}
    keep = set(order)

    edges = (
        dataset.transactions.lazy()
        .filter(pl.col("timestamp") <= sample.incident.complaint_time)
        .filter(pl.col("src").is_in(keep) & pl.col("dst").is_in(keep))
        .select("src", "dst", "amount", "timestamp", "channel")
        .with_columns(pl.col("timestamp").dt.epoch(time_unit="s").alias("epoch"))
        .collect()
    )

    if edges.height == 0:
        return gnn.GraphSample(
            x=sample.matrix.values,
            edge_index=np.zeros((2, 0), dtype=np.int64),
            edge_attr=np.zeros((0, gnn.EDGE_FEATURE_DIM), dtype=np.float32),
            y=sample.labels,
            layer=sample.layer_index,
            account_ids=sample.matrix.account_ids,
        )

    src = np.array([order[s] for s in edges["src"].to_list()], dtype=np.int64)
    dst = np.array([order[d] for d in edges["dst"].to_list()], dtype=np.int64)
    epochs = edges["epoch"].to_numpy()
    hours = edges["timestamp"].dt.hour().to_numpy()
    night_start, night_end = settings.night_hours

    edge_attr = gnn.encode_edges(
        amounts=edges["amount"].to_numpy(),
        delays_seconds=np.maximum(until_epoch - epochs, 0),
        channels=edges["channel"].to_list(),
        night=(hours >= night_start) | (hours < night_end),
    )
    return gnn.GraphSample(
        x=sample.matrix.values,
        edge_index=np.vstack([src, dst]),
        edge_attr=edge_attr,
        y=sample.labels,
        layer=sample.layer_index,
        account_ids=sample.matrix.account_ids,
    )


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------


def run(train_gnn_tier: bool = True) -> dict[str, object]:
    started = time.perf_counter()
    dataset = load_dataset()
    index = transaction_index()

    train_incidents = episodes_for(holdout=False, dataset=dataset)
    holdout_incidents = episodes_for(holdout=True, dataset=dataset)
    log.info(
        "%d training incidents, %d held-out incidents",
        len(train_incidents),
        len(holdout_incidents),
    )

    train_samples = build_samples(train_incidents, dataset, index)
    holdout_samples = build_samples(holdout_incidents, dataset, index)
    if not train_samples or not holdout_samples:
        raise RuntimeError("not enough incidents to train on")

    features, labels, groups = stack(train_samples)
    detector, gbdt_metrics = train_detector(features, labels, groups)
    detector.save(settings.detector_path, settings.detector_meta_path)

    tiers: list[dict[str, object]] = [
        evaluate_tier(
            "rules (bank practice)",
            holdout_samples,
            [baseline_rules.rule_scores(s.matrix) for s in holdout_samples],
        ),
        evaluate_tier(
            "lightgbm",
            holdout_samples,
            [detector.score(s.matrix) for s in holdout_samples],
        ),
    ]

    gnn_metrics: dict[str, float] = {}
    if train_gnn_tier and gnn.is_available():
        try:
            tier, gnn_metrics = _train_and_score_gnn(
                train_samples, holdout_samples, dataset
            )
            tiers.append(tier)
        except (RuntimeError, ValueError) as exc:
            log.warning("GNN tier skipped: %s", exc)
    elif train_gnn_tier:
        log.info("PyTorch Geometric not installed -- shipping on LightGBM alone")

    rings_report = _score_rings(holdout_samples, detector, dataset)
    contrast = _contrast(holdout_samples, dataset)

    report: dict[str, object] = {
        "generated_seconds": round(time.perf_counter() - started, 1),
        "holdout_rings": list(settings.holdout_ring_ids),
        "n_train_incidents": len(train_samples),
        "n_holdout_incidents": len(holdout_samples),
        "gbdt": gbdt_metrics,
        "gnn": gnn_metrics,
        "tiers": tiers,
        "rings": rings_report,
        "hard_negatives": contrast,
    }
    settings.detector_report_path.parent.mkdir(parents=True, exist_ok=True)
    settings.detector_report_path.write_text(
        json.dumps(report, indent=2, default=float), encoding="utf-8"
    )
    return report


def _train_and_score_gnn(
    train_samples: list[IncidentSample],
    holdout_samples: list[IncidentSample],
    dataset: Dataset,
) -> tuple[dict[str, object], dict[str, float]]:
    from app.graphstore.trace import to_epoch

    encoded_train = [
        encode_sample(s, dataset, to_epoch(s.incident.complaint_time))
        for s in train_samples
    ]
    model, metrics = gnn.train_gnn(encoded_train)
    gnn.save_gnn(model, settings.gnn_path)

    scores = [
        gnn.score_gnn(
            model, encode_sample(s, dataset, to_epoch(s.incident.complaint_time))
        )
        for s in holdout_samples
    ]
    return evaluate_tier("graphsage (gnn)", holdout_samples, scores), metrics


def _score_rings(
    samples: list[IncidentSample], detector: Detector, dataset: Dataset
) -> dict[str, object]:
    """Run ring discovery on the largest held-out incident and score it.

    Clustering is run over the *flagged* population, not every account in
    reach. That is how it would be used -- an analyst clusters the accounts the
    detector surfaced, not the whole bank -- and it is also the only version of
    the question that means anything. Feeding Louvain 5,000 accounts of which
    3% are mules mostly measures how it partitions ordinary retail traffic.
    """
    biggest = max(samples, key=lambda s: len(s.matrix.account_ids))
    all_scores = detector.score(biggest.matrix)
    accounts = [
        account
        for account, score in zip(biggest.matrix.account_ids, all_scores)
        if score >= settings.ring_cluster_threshold
    ]
    if len(accounts) < settings.min_ring_size:
        accounts = list(biggest.matrix.account_ids)

    edges = (
        dataset.transactions.lazy()
        .filter(pl.col("timestamp") <= biggest.incident.complaint_time)
        .filter(pl.col("src").is_in(set(accounts)) | pl.col("dst").is_in(set(accounts)))
        .select("src", "dst", "amount", "timestamp", "channel")
        .collect()
    )
    scores = {
        account: float(score)
        for account, score in zip(biggest.matrix.account_ids, all_scores)
    }
    discovered, assignment = detect_rings(accounts, edges, scores, dataset)

    quality = ring_ari(assignment, dataset)
    return {
        "incident": biggest.incident.incident_id,
        "accounts_clustered": len(accounts),
        "communities_found": len(discovered),
        "largest_community": max((r.size for r in discovered), default=0),
        **quality,
    }


def _contrast(samples: list[IncidentSample], dataset: Dataset) -> dict[str, object]:
    biggest = max(samples, key=lambda s: len(s.matrix.account_ids))
    return contrast_report(biggest.matrix, dataset.labels, dataset)


def main() -> None:
    logging.basicConfig(level="INFO", format="%(asctime)s  %(message)s")
    report = run()

    print("\nDetection tiers, scored on held-out rings "
          f"({', '.join(settings.holdout_ring_ids)})")
    print(f"{report['n_holdout_incidents']} held-out incidents, "
          f"{report['n_train_incidents']} used for training\n")
    print(format_table(report["tiers"]))  # type: ignore[arg-type]

    rings = report["rings"]
    assert isinstance(rings, dict)
    print(
        f"\nRing discovery on {rings['incident']}: "
        f"{rings['communities_found']} communities over "
        f"{rings['accounts_clustered']} accounts, "
        f"ARI {float(rings['ari']):.3f} against ground truth"
    )
    print()
    print(format_contrast(report["hard_negatives"]))  # type: ignore[arg-type]
    print(f"\nWrote {settings.detector_report_path}")


if __name__ == "__main__":
    main()
