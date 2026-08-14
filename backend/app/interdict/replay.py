"""Counterfactual replay: what a freeze plan actually achieved.

The solver plans against its own forecast. This module scores it against what
really happened -- the recorded transactions after the complaint time, replayed
with the freezes applied. If the forecast was wrong, this is where that shows
up as a worse number, which is the entire point of separating the two.

Grading a plan against the rollouts that produced it would be marking your own
homework, and every recovery figure in the benchmark would be a statement about
the propagation model rather than about the system.

**What counts as recovered.** Only tainted rupees that a freeze actually
stopped from leaving. Money that happens to still be sitting in an unfrozen
account when the horizon ends is reported separately as `residual` -- it is not
recovered, nobody has secured it, and counting it would flatter every policy
including the do-nothing baseline.

**The adversary can adapt.** When a transfer is blocked, a real operator does
not shrug and go home; they try another account they control. With
`adversary_reroute_prob` above zero the replay reroutes blocked money to a
different counterparty after a delay, and that retry can be blocked in turn.
The benchmark reports results both ways, because assuming a passive adversary
is the most flattering assumption available and it should not pass unstated.
"""

from __future__ import annotations

import heapq
import logging
from dataclasses import dataclass, field

import numpy as np

from app.config import settings
from app.graphstore.trace import TaintState, TransactionIndex, transaction_index
from app.interdict.greedy import FreezePlan

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Freeze:
    """An instruction in force against one account."""

    account_id: str
    action: str
    issue_at_minute: int

    @property
    def effectiveness(self) -> float:
        return settings.action_effectiveness[self.action]


@dataclass
class MinuteFrame:
    """One simulated minute, as streamed to the console."""

    minute: int
    flows: list[dict[str, object]] = field(default_factory=list)
    frozen: list[str] = field(default_factory=list)
    recovered_inr: float = 0.0
    leaked_inr: float = 0.0
    at_risk_inr: float = 0.0


@dataclass
class ReplayResult:
    """What actually happened under a plan."""

    recovered_inr: float
    leaked_inr: float
    residual_inr: float
    already_gone_inr: float
    amount_inr: float
    frozen_accounts: tuple[str, ...]
    innocent_frozen: int
    mules_frozen: int
    first_freeze_minute: int | None
    blocked_transfers: int
    rerouted_transfers: int
    frames: tuple[MinuteFrame, ...] = ()

    @property
    def recovery_rate(self) -> float:
        return self.recovered_inr / self.amount_inr if self.amount_inr > 0 else 0.0


def replay(
    state: TaintState,
    plan: FreezePlan,
    horizon_minutes: int,
    mule_ids: frozenset[str],
    index: TransactionIndex | None = None,
    reroute_prob: float | None = None,
    collect_frames: bool = False,
) -> ReplayResult:
    """Continue the incident from the complaint time with `plan` in force.

    `state` is the taint position at the complaint, produced by `trace_taint`.
    Replay picks up from there, so nothing before the complaint is re-simulated
    and no freeze can retroactively affect it.
    """
    idx = index if index is not None else transaction_index()
    reroute = (
        settings.adversary_reroute_prob if reroute_prob is None else reroute_prob
    )

    freezes = {
        step.account_id: Freeze(
            account_id=step.account_id,
            action=step.action,
            issue_at_minute=step.issue_at_minute,
        )
        for step in plan.steps
    }
    # Seeded from the incident alone, so a policy comparison is never decided
    # by luck in the effectiveness draws -- every policy meets the same coin
    # flips in the same order.
    rng = np.random.default_rng((state.t0 ^ settings.master_seed) % (2**32))

    end = state.t0 + horizon_minutes * 60
    held = dict(state.held)
    through = dict(state.through)
    recovered_by: dict[str, float] = {}
    leaked = 0.0
    blocked = 0
    rerouted = 0
    retries: dict[str, int] = {}

    per_minute: dict[int, MinuteFrame] = {}
    # Running totals for the console, banked at the minute they happen.
    leaked_at: dict[int, float] = {}
    secured_at: dict[int, float] = {}

    def minute_of(epoch: int) -> int:
        return int((epoch - state.t0) // 60)

    def frame_for(minute: int) -> MinuteFrame:
        frame = per_minute.get(minute)
        if frame is None:
            frame = MinuteFrame(minute=minute)
            per_minute[minute] = frame
        return frame

    # Re-arm the event loop from wherever the money currently sits.
    queue: list[tuple[int, str, int]] = []
    entered: set[str] = set()
    for account in held:
        if held[account] > settings.taint_floor_inr:
            entered.add(account)
            _arm(queue, idx, account, state.until, end)

    # Injected retries from the adaptive adversary, kept in the same timeline.
    injected: list[tuple[int, str, str, float]] = []

    while queue or injected:
        if injected and (not queue or injected[0][0] <= queue[0][0]):
            when, src, dst, amount = heapq.heappop(injected)  # type: ignore[assignment]
            _settle(
                held, through, src, dst, amount, when, idx, minute_of, frame_for,
                collect_frames,
            )
            if dst in idx.exits:
                leaked += amount
                leaked_at[minute_of(when)] = (
                    leaked_at.get(minute_of(when), 0.0) + amount
                )
            elif dst not in entered:
                entered.add(dst)
                _arm(queue, idx, dst, when, end)
            continue

        when, account, cursor = heapq.heappop(queue)
        edges = idx.out[account]
        _arm_next(queue, edges, account, cursor + 1, end)

        available = held.get(account, 0.0)
        if available <= settings.taint_floor_inr:
            continue

        share = _taint_share(state, idx, through, account, when, available)
        if share < settings.taint_min_share:
            continue

        moved = min(available, float(edges.amount[cursor]) * share)
        if moved <= settings.taint_floor_inr:
            continue

        minute = minute_of(when)
        freeze = freezes.get(account)

        if freeze is not None and freeze.issue_at_minute <= minute:
            if rng.random() < freeze.effectiveness:
                # Stopped. The money stays put and is recoverable.
                blocked += 1
                secured_at[minute] = secured_at.get(minute, 0.0) + moved
                if reroute > 0 and rng.random() < reroute:
                    retried = retries.get(account, 0)
                    target = _alternate_target(rng, idx, account, freezes)
                    if retried < settings.adversary_max_retries and target:
                        retries[account] = retried + 1
                        delay = int(
                            rng.integers(*settings.adversary_reroute_delay_minutes)
                        )
                        later = when + delay * 60
                        if later <= end:
                            # The retry succeeded in leaving, so it was never
                            # really secured -- take it back off the tally.
                            rerouted += 1
                            secured_at[minute] -= moved
                            held[account] = available - moved
                            heapq.heappush(injected, (later, account, target, moved))
                continue

        dst = edges.dst[cursor]
        held[account] = available - moved
        _record(
            through, dst, moved, minute, frame_for, collect_frames, account,
            float(edges.amount[cursor]),
        )

        if dst in idx.exits:
            leaked += moved
            leaked_at[minute] = leaked_at.get(minute, 0.0) + moved
            continue

        held[dst] = held.get(dst, 0.0) + moved
        if dst not in entered:
            entered.add(dst)
            _arm(queue, idx, dst, when, end)

    # Money sitting in a frozen account has been secured; money sitting in an
    # unfrozen account is merely still there, and nobody has done anything
    # about it.
    for account, amount in held.items():
        if amount <= settings.taint_floor_inr:
            continue
        if account in freezes:
            recovered_by[account] = amount

    recovered = sum(recovered_by.values())
    residual = sum(
        amount
        for account, amount in held.items()
        if account not in freezes and amount > settings.taint_floor_inr
    )

    frozen = tuple(step.account_id for step in plan.steps)
    result = ReplayResult(
        recovered_inr=round(recovered, 2),
        leaked_inr=round(state.exited + leaked, 2),
        residual_inr=round(residual, 2),
        already_gone_inr=round(state.exited, 2),
        amount_inr=state.amount_inr,
        frozen_accounts=frozen,
        innocent_frozen=sum(1 for a in frozen if a not in mule_ids),
        mules_frozen=sum(1 for a in frozen if a in mule_ids),
        first_freeze_minute=(
            min((s.issue_at_minute for s in plan.steps), default=None)
        ),
        blocked_transfers=blocked,
        rerouted_transfers=rerouted,
        frames=_finalise_frames(
            per_minute, plan, horizon_minutes, state, leaked_at, secured_at, recovered
        )
        if collect_frames
        else (),
    )
    return result


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _arm(
    queue: list[tuple[int, str, int]],
    index: TransactionIndex,
    account: str,
    since: int,
    end: int,
) -> None:
    edges = index.out.get(account)
    if edges is None:
        return
    cursor = int(np.searchsorted(edges.time, since, side="left"))
    _arm_next(queue, edges, account, cursor, end)


def _arm_next(
    queue: list[tuple[int, str, int]],
    edges: object,
    account: str,
    cursor: int,
    end: int,
) -> None:
    if cursor >= len(edges.dst):  # type: ignore[attr-defined]
        return
    when = int(edges.time[cursor])  # type: ignore[attr-defined]
    if when > end:
        return
    heapq.heappush(queue, (when, account, cursor))


def _taint_share(
    state: TaintState,
    index: TransactionIndex,
    through: dict[str, float],
    account: str,
    when: int,
    available: float,
) -> float:
    total_in = index.inflow_between(account, state.t0, when)
    tainted_in = through.get(account, 0.0)
    if account == state.victim:
        total_in = max(total_in, 0.0) + state.amount_inr
    denominator = max(total_in, tainted_in, available)
    if denominator <= 0.0:
        return 0.0
    return min(1.0, tainted_in / denominator)


def _alternate_target(
    rng: np.random.Generator,
    index: TransactionIndex,
    account: str,
    freezes: dict[str, Freeze],
) -> str | None:
    """Another account this operator has used before and that is not frozen."""
    edges = index.out.get(account)
    if edges is None or not edges.dst:
        return None
    options = [d for d in set(edges.dst) if d not in freezes]
    if not options:
        return None
    return str(rng.choice(sorted(options)))


def _record(
    through: dict[str, float],
    dst: str,
    moved: float,
    minute: int,
    frame_for,
    collect_frames: bool,
    src: str,
    gross: float,
) -> None:
    through[dst] = through.get(dst, 0.0) + moved
    if collect_frames:
        frame_for(minute).flows.append(
            {"src": src, "dst": dst, "amount": round(gross, 2), "tainted": round(moved, 2)}
        )


def _settle(
    held: dict[str, float],
    through: dict[str, float],
    src: str,
    dst: str,
    amount: float,
    when: int,
    index: TransactionIndex,
    minute_of,
    frame_for,
    collect_frames: bool,
) -> None:
    """Apply a rerouted transfer the adversary managed to push through."""
    if dst not in index.exits:
        held[dst] = held.get(dst, 0.0) + amount
    _record(through, dst, amount, minute_of(when), frame_for, collect_frames, src, amount)


def _finalise_frames(
    per_minute: dict[int, MinuteFrame],
    plan: FreezePlan,
    horizon_minutes: int,
    state: TaintState,
    leaked_at: dict[int, float],
    secured_at: dict[int, float],
    final_recovered: float,
) -> tuple[MinuteFrame, ...]:
    """Fill in every minute of the horizon with running totals for the console.

    The three money figures always sum to the stolen amount, at every frame.
    A judge watching the counters tick will add them up, and they have to
    reconcile at every point in the replay, not just at the end.
    """
    freezes_by_minute: dict[int, list[str]] = {}
    for step in plan.steps:
        freezes_by_minute.setdefault(step.issue_at_minute, []).append(step.account_id)

    frames: list[MinuteFrame] = []
    active: list[str] = []
    running_leaked = state.exited
    running_secured = 0.0

    for minute in range(horizon_minutes + 1):
        frame = per_minute.get(minute) or MinuteFrame(minute=minute)
        active.extend(freezes_by_minute.get(minute, ()))
        running_leaked += leaked_at.get(minute, 0.0)
        running_secured += secured_at.get(minute, 0.0)

        frame.frozen = list(active)
        frame.leaked_inr = round(running_leaked, 2)
        frame.recovered_inr = round(running_secured, 2)
        frame.at_risk_inr = round(
            max(0.0, state.amount_inr - running_leaked - running_secured), 2
        )
        frames.append(frame)

    # Taint still parked inside frozen accounts at the horizon is recovered too,
    # but it is only known at the end. Bank it on the final frame rather than
    # inventing a minute for it.
    if frames:
        last = frames[-1]
        last.recovered_inr = round(final_recovered, 2)
        last.at_risk_inr = round(
            max(0.0, state.amount_inr - last.leaked_inr - last.recovered_inr), 2
        )

    return tuple(frames)
