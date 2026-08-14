"""Transfer test: score the trained detector against a foreign dataset.

    python -m app.eval.external path/to/transactions.csv [path/to/accounts.csv]

Everything else in this repository is measured on data this repository
generated. That is a real limitation, and the honest way to bound it is to run
the detector against somebody else's simulator and report whatever comes out --
including a bad number. "0.99 AUC-PR on our data, 0.6X on IBM AMLSim, and here
is exactly why" is worth more to a serious reader than another point of
internal accuracy.

WHAT THIS DOES NOT DO. It does not retrain, and it does not tune anything to
the foreign data. It rebuilds this system's features from the foreign
transaction log and asks the *already trained* model for scores. A transfer
test that fits to the target is not a transfer test.

SCHEMA. AMLSim's own output and the various Kaggle exports of it do not agree
on column names, so the mapping is explicit and configurable rather than
guessed. If a required column is missing the loader says which, and lists what
it actually found, instead of failing somewhere deep in a join.

Run it and paste the number into the README. If it is bad, say so there.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from app.config import settings

log = logging.getLogger(__name__)

#: Column aliases seen across AMLSim's own output and its Kaggle exports.
#: Extend these rather than renaming somebody else's file.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "src": ("orig_acct", "nameOrig", "SENDER_ACCOUNT_ID", "src", "source"),
    "dst": ("bene_acct", "nameDest", "RECEIVER_ACCOUNT_ID", "dst", "target"),
    "amount": ("base_amt", "amount", "TX_AMOUNT", "AMOUNT"),
    "timestamp": ("tran_timestamp", "step", "TIMESTAMP", "timestamp"),
    "is_sar": ("is_sar", "isFraud", "IS_FRAUD", "IS_SAR", "is_fraud", "label"),
}


@dataclass
class TransferResult:
    rows: int
    accounts: int
    positives: int
    prevalence: float
    auc_pr: float
    precision_at_100: float
    note: str

    def to_dict(self) -> dict[str, object]:
        return {
            "rows": self.rows,
            "accounts": self.accounts,
            "positives": self.positives,
            "prevalence": round(self.prevalence, 6),
            "auc_pr": round(self.auc_pr, 4),
            "precision_at_100": round(self.precision_at_100, 4),
            "note": self.note,
        }


def _resolve(frame: pl.DataFrame, field: str) -> str:
    """Find the column this dataset uses for `field`, or say what it has."""
    for candidate in COLUMN_ALIASES[field]:
        if candidate in frame.columns:
            return candidate
    raise SystemExit(
        f"Could not find a '{field}' column. Tried {COLUMN_ALIASES[field]}.\n"
        f"The file has: {frame.columns}\n"
        "Add the right name to COLUMN_ALIASES in app/eval/external.py."
    )


def load_transactions(path: Path) -> pl.DataFrame:
    """Normalise a foreign transaction log into src/dst/amount/epoch/is_sar."""
    if not path.exists():
        raise SystemExit(f"No such file: {path}")

    raw = pl.read_csv(path, infer_schema_length=10_000)
    columns = {field: _resolve(raw, field) for field in COLUMN_ALIASES}

    frame = raw.select(
        pl.col(columns["src"]).cast(pl.Utf8).alias("src"),
        pl.col(columns["dst"]).cast(pl.Utf8).alias("dst"),
        pl.col(columns["amount"]).cast(pl.Float64).alias("amount"),
        pl.col(columns["timestamp"]).alias("raw_time"),
        pl.col(columns["is_sar"]).alias("raw_label"),
    )

    # AMLSim emits an integer step; the Kaggle exports emit a timestamp string.
    # Both are monotone in time, which is all the features need.
    if frame["raw_time"].dtype in (pl.Int64, pl.Int32, pl.Float64):
        frame = frame.with_columns(
            (pl.col("raw_time").cast(pl.Int64) * 3600).alias("epoch")
        )
    else:
        frame = frame.with_columns(
            pl.col("raw_time")
            .str.to_datetime(strict=False)
            .dt.epoch(time_unit="s")
            .alias("epoch")
        )

    # Labels arrive as 0/1, true/false, or "SAR"/"NORMAL" depending on export.
    label = frame["raw_label"]
    if label.dtype == pl.Utf8:
        frame = frame.with_columns(
            pl.col("raw_label")
            .str.to_lowercase()
            .is_in(["1", "true", "sar", "yes"])
            .alias("is_sar")
        )
    else:
        frame = frame.with_columns((pl.col("raw_label").cast(pl.Float64) > 0).alias("is_sar"))

    return frame.drop("raw_time", "raw_label").drop_nulls(["src", "dst", "amount", "epoch"])


def account_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Per-account aggregates this detector can actually consume.

    Deliberately the *intersection* of what both datasets carry. The foreign
    log has no devices, no KYC tier and no dormancy, which is itself part of
    the finding: several of the features carrying this detector's performance
    simply do not exist over there, and a transfer number measured without
    them is a lower bound on a different model, not on this one.
    """
    out = frame.group_by("src").agg(
        pl.len().alias("out_count"),
        pl.col("amount").sum().alias("out_amount"),
        pl.col("amount").mean().alias("out_mean"),
        pl.col("dst").n_unique().alias("out_degree"),
        pl.col("epoch").min().alias("first_out"),
        pl.col("epoch").max().alias("last_out"),
    ).rename({"src": "account_id"})

    inbound = frame.group_by("dst").agg(
        pl.len().alias("in_count"),
        pl.col("amount").sum().alias("in_amount"),
        pl.col("src").n_unique().alias("in_degree"),
        pl.col("epoch").min().alias("first_in"),
    ).rename({"dst": "account_id"})

    labels = (
        frame.filter(pl.col("is_sar"))
        .select(pl.col("dst").alias("account_id"))
        .unique()
        .with_columns(pl.lit(True).alias("is_sar"))
    )

    joined = (
        out.join(inbound, on="account_id", how="full", coalesce=True)
        .join(labels, on="account_id", how="left")
        .fill_null(0)
        .with_columns(
            (pl.col("out_amount") / (pl.col("in_amount") + 1.0)).alias("forward_ratio"),
            ((pl.col("first_out") - pl.col("first_in")) / 60.0).alias("residence_minutes"),
        )
    )
    return joined.with_columns(pl.col("is_sar").cast(pl.Boolean).fill_null(False))


def average_precision(scores: np.ndarray, labels: np.ndarray) -> float:
    """AUC-PR by the step-wise definition, so it needs no sklearn import."""
    order = np.argsort(-scores)
    truth = labels[order]
    positives = truth.sum()
    if positives == 0:
        return 0.0
    cumulative = np.cumsum(truth)
    precision = cumulative / np.arange(1, len(truth) + 1)
    return float((precision * truth).sum() / positives)


def score(frame: pl.DataFrame) -> TransferResult:
    """Rank accounts by a transferable proxy and report what that achieves.

    IMPORTANT AND STATED PLAINLY: this is *not* the LightGBM model. That model
    is trained on features -- device sharing, dormancy break, KYC tier, taint
    share -- which the foreign log does not contain, so it cannot be applied
    here without inventing values for them, and inventing them would make the
    resulting number meaningless. What is scored instead is the transferable
    part of the signal: fan-out and fast forwarding of received funds.

    So the number this prints is a floor on what a *retrained* model would get,
    not a measurement of the shipped detector. Report it as such.
    """
    features = account_features(frame)
    if features.height == 0:
        raise SystemExit("No accounts after aggregation -- check the input file.")

    # Fan-out and speed of forwarding: the two tells that survive the crossing.
    proxy = (
        features.select(
            pl.col("out_degree").cast(pl.Float64),
            pl.col("forward_ratio").cast(pl.Float64),
            pl.col("residence_minutes").cast(pl.Float64),
            pl.col("is_sar"),
        )
        .with_columns(
            (
                pl.col("out_degree").log1p()
                + pl.col("forward_ratio").clip(0.0, 2.0)
                - (pl.col("residence_minutes").clip(0.0, 1440.0) / 1440.0)
            ).alias("proxy_score")
        )
    )

    scores = proxy["proxy_score"].to_numpy()
    labels = proxy["is_sar"].to_numpy().astype(float)

    ranked = np.argsort(-scores)[:100]
    return TransferResult(
        rows=frame.height,
        accounts=features.height,
        positives=int(labels.sum()),
        prevalence=float(labels.mean()),
        auc_pr=average_precision(scores, labels),
        precision_at_100=float(labels[ranked].mean()) if len(ranked) else 0.0,
        note=(
            "Structural proxy (fan-out + forwarding speed), not the shipped "
            "LightGBM model: the foreign log carries no device, dormancy, KYC "
            "or taint features, which are load-bearing for this detector. "
            "Treat this as a floor, and as evidence about how much of the "
            "signal is structural rather than about how well this model "
            "generalises."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transactions", type=Path)
    parser.add_argument(
        "--out",
        type=Path,
        default=settings.data_dir / "external_validation.json",
        help="Where to write the result. The Benchmark tab reads this.",
    )
    args = parser.parse_args(argv)

    frame = load_transactions(args.transactions)
    log.info("loaded %d transactions", frame.height)

    result = score(frame)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

    log.info(
        "\n%d accounts, %d flagged in truth (%.3f%%)\n"
        "AUC-PR            %.4f\n"
        "precision@100     %.4f\n\n%s\n\nwrote %s",
        result.accounts,
        result.positives,
        result.prevalence * 100,
        result.auc_pr,
        result.precision_at_100,
        result.note,
        args.out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
