"""The one interface all four detection systems are seen through.

The harness never imports a competitor. Each system lives in its own virtual
environment with its own pinned dependencies, and the harness talks to it as a
subprocess over newline-delimited JSON. That is what makes conflicting torch and
scikit-learn versions a non-problem, and it is why a non-Python competitor would
need no special handling.

    harness env                     model env
    -----------                     ---------
    Observation  --json-->  runner  --native calls-->  the model
    Prediction   <--json--  runner  <--native output--

An adapter is the harness-side half: it knows how to translate a canonical
Observation into whatever its repository expects, and how to normalise whatever
comes back into a Prediction. Both halves of that translation are per-repository
work, and both are logged, because a translator that quietly drops a field one
system could have used is the difference between a benchmark and an advert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

ScoreKind = Literal["continuous", "rule_count", "binary"]
Mode = Literal["streaming", "batch"]


@dataclass(frozen=True)
class Observation:
    """Everything visible at simulated time `t_sec`. Identical for all models.

    `transfers` is the **raw** transaction log restricted to the accounts in the
    case, not just the traced stolen money: a detection system is entitled to see
    an account's ordinary traffic, and several of them need it to compute
    velocity at all. Every row satisfies `t_offset_sec <= t_sec`, and the
    truncation happens once, here, rather than inside each adapter -- which is
    the only way to be sure no system is quietly given the future.
    """

    case_id: str
    t_sec: int
    #: Static account attributes: id, bank, kyc_level, opened_at, device
    #: fingerprint, ip prefix, archetype. No labels.
    accounts: list[dict]
    #: Raw transactions with t_offset_sec <= t_sec. Offsets may be negative:
    #: history before the incident is visible, because a bank has it.
    transfers: list[dict]
    #: Derived adjacency over `transfers`, as (src, dst, amount, t_offset_sec).
    graph_edges: list[tuple]
    #: Accounts already known to be mules from previously worked cases. This is
    #: the watchlist a deployed system would have, and it is built from training
    #: rings only -- so on a held-out ring every system starts cold.
    known_mules: list[str] = field(default_factory=list)
    #: Seconds after t0 at which the victim reported. Some systems are only
    #: invoked by a complaint; all of them are allowed to know when it landed.
    complaint_offset_sec: int = 0

    def to_json(self) -> dict:
        return {
            "case_id": self.case_id,
            "t_sec": self.t_sec,
            "accounts": self.accounts,
            "transfers": self.transfers,
            "known_mules": self.known_mules,
            "complaint_offset_sec": self.complaint_offset_sec,
        }

    @classmethod
    def from_json(cls, payload: dict) -> "Observation":
        transfers = payload["transfers"]
        return cls(
            case_id=payload["case_id"],
            t_sec=int(payload["t_sec"]),
            accounts=payload["accounts"],
            transfers=transfers,
            graph_edges=[
                (t["from"], t["to"], float(t["amount_inr"]), int(t["t_offset_sec"]))
                for t in transfers
            ],
            known_mules=payload.get("known_mules", []),
            complaint_offset_sec=int(payload.get("complaint_offset_sec", 0)),
        )


@dataclass(frozen=True)
class Prediction:
    """What one system said about one observation."""

    #: account_id -> [0,1], higher = more mule-like.
    scores: dict[str, float]
    #: account_id -> [{feature, contribution, direction, human_text}]
    attributions: dict[str, list[dict]]
    #: Real compute time inside the model environment, for the runtime report.
    wall_ms: float
    #: Populated when a system produces a hard label of its own, independent of
    #: any threshold the harness might apply. Only the PoC's IsolationForest
    #: does this today, and it is what its `native` operating point is built on.
    native_flags: dict[str, bool] = field(default_factory=dict)
    status: str = "ok"
    error: str = ""

    def to_json(self) -> dict:
        return {
            "scores": self.scores,
            "attributions": self.attributions,
            "wall_ms": self.wall_ms,
            "native_flags": self.native_flags,
            "status": self.status,
            "error": self.error,
        }

    @classmethod
    def from_json(cls, payload: dict) -> "Prediction":
        return cls(
            scores={k: float(v) for k, v in payload.get("scores", {}).items()},
            attributions=payload.get("attributions", {}),
            wall_ms=float(payload.get("wall_ms", 0.0)),
            native_flags=payload.get("native_flags", {}),
            status=payload.get("status", "ok"),
            error=payload.get("error", ""),
        )

    @classmethod
    def failed(cls, reason: str) -> "Prediction":
        return cls(scores={}, attributions={}, wall_ms=0.0, status="error", error=reason)


class Detector(Protocol):
    """The harness-side view of a detection system."""

    id: str
    #: The project's real name, as its authors wrote it. Never a rank, never a
    #: label chosen by us. Blind mode substitutes "System A".."System D" at the
    #: presentation layer only -- the numbers are computed against these ids.
    name: str
    score_kind: ScoreKind
    mode: Mode

    def fit(self, train_split_path: str) -> None:
        """Train on our train split, using the repository's own training code."""

    def score(self, obs: Observation) -> Prediction:
        """Score every account in `obs`, seeing only what `obs` contains."""


# ---------------------------------------------------------------------------
# score normalisation
# ---------------------------------------------------------------------------


def rank_normalise(scores: dict[str, float]) -> dict[str, float]:
    """Map scores onto [0,1] by rank, per case.

    Rank normalisation is the default because it is strictly monotone: it cannot
    reorder anything a model said, so it cannot flatter or damage one. It only
    makes a threshold mean the same thing across systems whose raw outputs live
    on completely different scales -- a calibrated probability, a weighted rule
    sum out of 100, and a risk score that is a sum of three unbounded terms.

    Ties share the midpoint of the rank block they occupy, so a model that
    genuinely cannot separate two accounts is not given a spurious ordering.
    """
    if not scores:
        return {}
    if len(scores) == 1:
        return {next(iter(scores)): 1.0}

    ordered = sorted(scores.items(), key=lambda kv: (kv[1], kv[0]))
    out: dict[str, float] = {}
    n = len(ordered)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        # Midpoint of the tied block, mapped into (0, 1].
        value = ((i + j) / 2.0 + 1.0) / n
        for k in range(i, j + 1):
            out[ordered[k][0]] = round(value, 6)
        i = j + 1
    return out


def rule_fraction(fired: dict[str, bool], weights: dict[str, float]) -> float:
    """Weighted fraction of rules fired, for rule engines.

    Monotone in severity, so thresholding still means something, but the model
    is marked `rule_count` so the Arena can say what kind of number it is
    showing rather than passing it off as a probability.
    """
    total = sum(weights.values()) or 1.0
    return sum(weights[name] for name, on in fired.items() if on) / total
