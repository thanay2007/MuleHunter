"""Replaying a case forward in time, so `t_decision_sec` is earned.

The Arena's whole drama is who flags first. That number has to come from
somewhere real, so it comes from here: the case is fed forward tick by tick,
every system is asked what it thinks at each tick, and the first tick at which
an account crosses that system's operating point is its decision time.

Two honesty rules govern this file.

**A batch model is not penalised by harness choice.** If a system genuinely
needs the whole window, its decision time is the end of the window it requires,
it is recorded as `mode: "batch"`, and the Arena badges it as deciding at window
close. A streaming model deciding earlier is a real operational advantage; a
batch model made to look slow because we chose to tick it is not, and the two
have to be told apart on screen.

**A decision is not an instruction.** Crossing a threshold is when a system
*decides*; the freeze still has to be dispatched to the holding bank, and only
so many can be in flight at once. That dispatch model is taken from the
backend's own settings and applied identically to all four systems, so a model
that ranks the right account first gets its freeze in earlier than one that
ranks it eighth. Both timestamps are recorded: `t_flag_sec` (decided) and
`t_decision_sec` (in force).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .contract import Observation, Prediction
from .observation import build_observation, tick_schedule

log = logging.getLogger("bench.replay")

#: Dispatch model, from backend/app/config.py. An instruction takes this long to
#: reach the holding bank, and this many can be in flight at once.
DISPATCH_LATENCY_SEC = 90
DISPATCH_PARALLEL = 4


@dataclass
class ReplayResult:
    model_id: str
    case_id: str
    #: account_id -> {t_flag_sec, t_decision_sec, score, rank, attributions}
    flags: dict[str, dict] = field(default_factory=dict)
    #: Final-tick score for every account, which is what calibration reads.
    final_scores: dict[str, float] = field(default_factory=dict)
    final_attributions: dict[str, list[dict]] = field(default_factory=dict)
    native_flags: dict[str, bool] = field(default_factory=dict)
    wall_ms: list[float] = field(default_factory=list)
    ticks: int = 0
    status: str = "ok"
    error: str = ""

    def to_json(self) -> dict:
        return {
            "model_id": self.model_id,
            "case_id": self.case_id,
            "flags": self.flags,
            "final_scores": self.final_scores,
            "final_attributions": self.final_attributions,
            "native_flags": self.native_flags,
            "wall_ms": self.wall_ms,
            "ticks": self.ticks,
            "status": self.status,
            "error": self.error,
        }

    @classmethod
    def from_json(cls, payload: dict) -> "ReplayResult":
        return cls(**payload)


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------


def cache_key(model_id: str, case: dict, adapter_fingerprint: str, tick_sec: int) -> str:
    """Hash of everything that could change the answer.

    Adapter source, environment lock, the case itself, and the tick schedule. If
    none of those moved, the cached result is still correct, and a full re-run
    from cache is what makes it possible to iterate the night before.
    """
    digest = hashlib.sha256()
    digest.update(model_id.encode())
    digest.update(adapter_fingerprint.encode())
    digest.update(str(tick_sec).encode())
    digest.update(
        json.dumps(
            {
                "case_id": case["case_id"],
                "events": len(case["events"]),
                "pool": case["pool"],
                "t0": case["t0"],
                "complaint": case["complaint_offset_sec"],
            },
            sort_keys=True,
        ).encode()
    )
    return digest.hexdigest()[:24]


def cached(path: Path) -> ReplayResult | None:
    if not path.exists():
        return None
    try:
        return ReplayResult.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        log.warning("ignoring unreadable cache entry %s: %s", path.name, exc)
        return None


# ---------------------------------------------------------------------------
# the replay
# ---------------------------------------------------------------------------


def crosses(score: float, rank: int, threshold: float, budget: int | None) -> bool:
    """One definition of "this system has committed", shared by all of them."""
    if budget is not None and rank > budget:
        return False
    return score >= threshold


def replay(
    case: dict,
    detector,
    threshold: float,
    budget: int | None,
    tick_sec: int,
    normalise,
) -> ReplayResult:
    """Feed the case forward and record when each account first crossed.

    `normalise` is the score normaliser for this system's `score_kind` -- rank
    normalisation by default, which is monotone and so cannot reorder anything
    the system said.
    """
    result = ReplayResult(model_id=detector.id, case_id=case["case_id"])

    if detector.mode == "batch":
        # A batch system decides once, at the close of the window it needs. It is
        # still shown the whole observation; it simply has no earlier answer to
        # give, and inventing one for it would be the opposite of fair.
        moments = [int(case.get("t_end_sec") or case["horizon_sec"])]
    else:
        moments = tick_schedule(case, tick_sec)

    for t in moments:
        obs = build_observation(case, t)
        try:
            prediction = detector.score(obs)
        except Exception as exc:  # noqa: BLE001 -- a competitor failing is data
            result.status = "error"
            result.error = f"{type(exc).__name__}: {exc}"
            log.error("%s failed on %s at t=%d: %s", detector.id, case["case_id"], t, exc)
            return result

        if prediction.status != "ok":
            result.status = "error"
            result.error = prediction.error
            return result

        result.ticks += 1
        result.wall_ms.append(prediction.wall_ms)

        scores = normalise(prediction.scores)
        result.final_scores = scores
        result.final_attributions = prediction.attributions
        result.native_flags = prediction.native_flags

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        for rank, (account, score) in enumerate(ranked, start=1):
            if account in result.flags:
                continue
            if crosses(score, rank, threshold, budget):
                result.flags[account] = {
                    "t_flag_sec": int(t),
                    "score": round(float(score), 6),
                    "rank": rank,
                    "attributions": prediction.attributions.get(account, []),
                }

    _apply_dispatch(result, case)
    return result


def _apply_dispatch(result: ReplayResult, case: dict) -> None:
    """Turn a decision into an instruction that has actually reached a bank.

    Nothing can be frozen before the victim reports, however early a monitoring
    system suspected the account -- a bank does not freeze a customer because a
    model is uneasy. So the instruction clock starts at the complaint, and the
    queue drains at the dispatch rate. Applied identically to every system.
    """
    complaint = int(case["complaint_offset_sec"])
    order = sorted(
        result.flags.items(), key=lambda kv: (kv[1]["t_flag_sec"], kv[1]["rank"], kv[0])
    )
    for position, (account, record) in enumerate(order, start=1):
        wave = -(-position // DISPATCH_PARALLEL)  # ceil
        record["t_decision_sec"] = max(
            record["t_flag_sec"], complaint + wave * DISPATCH_LATENCY_SEC
        )
        record["dispatch_position"] = position
