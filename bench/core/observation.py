"""Building the view of a case at simulated time t, without leaking the future.

This is the most important file in the harness and the easiest one to get
quietly wrong. Every system's decision time comes from replaying the case
forward and asking it, again and again, "what do you think *now*". If any
feature handed to an early tick was computed over the whole case, the whole
latency comparison is fiction -- and nothing about it looks broken.

So there is exactly one truncation, it happens here, and `test_no_leakage.py`
asserts that building an observation at t is byte-identical to building it from
an event log that was truncated on disk before this module ever saw it.

Two things that look like leaks and are not:

  * **Negative offsets survive.** History from before the incident is visible,
    because a bank has it. `t_offset_sec <= t` keeps the past and drops only the
    future, which is the correct reading.
  * **Static account attributes survive.** Bank, KYC tier, opening date, device
    fingerprint: all of these were true before the fraud and are on file. What
    does *not* survive is anything derived from events -- account age and
    dormancy are recomputed here against the truncated log rather than copied
    from the canonical file, precisely so they cannot smuggle a later fact in.
"""

from __future__ import annotations

import bisect
from pathlib import Path

from .contract import Observation

#: A regular tick, in simulated seconds. Coarse enough that a full sweep across
#: four systems and a dozen cases finishes while you watch, fine enough that a
#: freeze landing one dispatch wave earlier is visible. Overridable per run.
DEFAULT_TICK_SEC = 30


def truncate(events: list[dict], t: int) -> list[dict]:
    """Every event at or before `t`. The single point of truncation."""
    # `events` is sorted by t_offset_sec when it comes out of canonical.py, so
    # this is a binary search rather than a scan -- which matters when a sweep
    # calls it a few thousand times.
    offsets = [e["t_offset_sec"] for e in events]
    return events[: bisect.bisect_right(offsets, t)]


def build_observation(case: dict, t: int) -> Observation:
    """The canonical view of `case` at simulated time `t`.

    Identical content for every system. Adapters translate it into whatever
    their repository expects; none of them gets to reach past it.
    """
    visible = truncate(case["events"], t)

    # Recomputed, never copied: the two account attributes that are functions of
    # the event log rather than of the account record.
    last_seen: dict[str, int] = {}
    for event in visible:
        last_seen[event["from"]] = event["t_offset_sec"]
        last_seen[event["to"]] = event["t_offset_sec"]

    accounts: list[dict] = []
    for record in case["accounts"]:
        row = dict(record)
        elapsed_days = t / 86400.0
        row["account_age_days"] = round(row["account_age_days"] + elapsed_days, 4)
        seen = last_seen.get(row["id"])
        if seen is None:
            # No transaction inside the visible window at all: the dormancy the
            # account record carried, plus however long the window has run.
            row["dormancy_days_before"] = round(
                row["dormancy_days_before"] + elapsed_days, 4
            )
        else:
            row["dormancy_days_before"] = round((t - seen) / 86400.0, 4)
        accounts.append(row)

    return Observation(
        case_id=case["case_id"],
        t_sec=int(t),
        accounts=accounts,
        transfers=visible,
        graph_edges=[
            (e["from"], e["to"], float(e["amount_inr"]), int(e["t_offset_sec"]))
            for e in visible
        ],
        known_mules=case.get("known_mules", []),
        complaint_offset_sec=int(case["complaint_offset_sec"]),
    )


def tick_schedule(case: dict, tick_sec: int = DEFAULT_TICK_SEC) -> list[int]:
    """When to ask the systems what they think.

    A regular grid, plus every moment something actually happened. The grid
    alone would step over a transfer and attribute the resulting change to the
    wrong second; the event times alone would leave long gaps where a
    time-decaying feature crosses a threshold unobserved. Both together are
    cheaper than a fine grid and strictly more faithful than either.

    Nothing before the incident is ticked. The systems still *see* the prior
    month -- it is in every observation -- but there is no decision to record
    before the money moves.
    """
    end = int(case.get("t_end_sec") or case["horizon_sec"])
    moments = {0, end}
    moments.update(range(0, end + 1, max(1, tick_sec)))
    for event in case["events"]:
        offset = int(event["t_offset_sec"])
        if 0 <= offset <= end:
            moments.add(offset)
            # One tick immediately after each event, so a system that reacts to
            # it is not credited with having reacted before it.
            moments.add(min(end, offset + 1))
    for cashout in case.get("cashout_events", []):
        offset = int(cashout["t_offset_sec"])
        if 0 <= offset <= end:
            moments.add(offset)
    moments.add(int(case["complaint_offset_sec"]))
    return sorted(m for m in moments if 0 <= m <= end)


def case_end(case: dict) -> int:
    """Where the replay stops.

    The horizon is six hours, but nothing happens in the last five of them and a
    scrubber that spends most of its travel on an empty timeline is a scrubber
    nobody can use.
    """
    if case.get("t_end_sec"):
        return int(case["t_end_sec"])
    latest = [int(case["complaint_offset_sec"])]
    latest += [int(t["t_offset_sec"]) for t in case["transfers"]]
    latest += [int(c["t_offset_sec"]) for c in case.get("cashout_events", [])]
    return min(int(case["horizon_sec"]), max(latest) + 900)


def write_truncated_log(case: dict, t: int, path: Path) -> Path:
    """Write the truncated event log to disk.

    Only used by the leak test, which rebuilds an observation from a log that
    was cut before `build_observation` ran and checks the two agree.
    """
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(truncate(case["events"], t)), encoding="utf-8")
    return path
