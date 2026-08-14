"""The freeze-frontier solver.

    maximise   R(S) = M - E[ money reaching an exit | freeze set S ]
    subject to |S| <= K                (freeze authority budget)
               sum of c(a) over S <= B (innocence budget)
               every freeze issued at or after the complaint time

**Why this has a guarantee.** Over the cached rollouts, a parcel of money is
recovered if any freeze on its path lands before it moves on. Writing
`e(action)` for how reliably an action stops a transfer, the probability a
parcel survives a freeze set is the product of `(1 - e)` over the freezes on
its path, so

    R(S) = sum over parcels of  value * (1 - product of (1 - e_i))

which is a probabilistic coverage function: monotone and submodular in `S`.
Greedy therefore attains at least `(1 - 1/e) ~ 0.632` of the optimum under the
cardinality budget. That bound is a real theorem about this objective, not a
figure of speech -- and `exact_cpsat.py` measures the actual gap on incidents
small enough to solve exactly, so the claim is checked rather than asserted.

With the innocence budget active the problem is a submodular knapsack, where
plain ratio-greedy has no such bound. The standard fix is implemented: run
ratio-greedy, separately take the best single affordable item, and return
whichever is better. That restores a `(1/2)(1 - 1/e)` guarantee.

**Why order matters.** Freeze instructions take time to reach a holding bank
and only so many can be issued at once, so the k-th freeze in the plan takes
effect later than the first. A later freeze intercepts strictly less money.
Greedy therefore does not choose a *set* and sort it -- it chooses each next
freeze knowing when that freeze would actually land.

**CELF.** Marginal gains only ever shrink: coverage grows as freezes are added,
and issue times slip later as the plan lengthens. A stale gain is therefore
always an upper bound on the true one, which makes lazy evaluation exact. It is
what keeps a 5,000-account incident inside the two-second budget.
"""

from __future__ import annotations

import heapq
import logging
import math
import time
from dataclasses import dataclass, field

import numpy as np

from app.config import settings
from app.interdict.propagate import RolloutSet

log = logging.getLogger(__name__)

ACTIONS: tuple[str, ...] = (
    "full_freeze",
    "outbound_hold",
    "step_up_verification",
)


@dataclass(frozen=True)
class FreezeOption:
    """One thing we could do to one account."""

    account_id: str
    action: str

    @property
    def effectiveness(self) -> float:
        return settings.action_effectiveness[self.action]

    @property
    def harm_weight(self) -> float:
        return settings.action_harm_weight[self.action]


@dataclass(frozen=True)
class FreezeStep:
    """One instruction in the issued plan."""

    rank: int
    account_id: str
    action: str
    issue_at_minute: int
    marginal_recovery_inr: float
    p_mule: float
    innocence_cost: float
    effectiveness: float


@dataclass
class FreezePlan:
    """The ordered plan, and what it is expected to achieve."""

    steps: list[FreezeStep] = field(default_factory=list)
    #: Rupees this plan keeps *inside* the banking system that would otherwise
    #: have left. The headline number, and the one that cannot be gamed.
    projected_recovery_inr: float = 0.0
    #: Rupees expected to leave the banking system despite the plan.
    projected_leak_inr: float = 0.0
    #: Rupees expected to sit under a freeze at the end of the window --
    #: including money that was never going to move. Under bank control, so
    #: returnable, but reported separately because it is a weaker claim.
    projected_secured_inr: float = 0.0
    innocent_accounts_frozen_expected: float = 0.0
    total_innocence_cost: float = 0.0
    solve_ms: float = 0.0
    evaluations: int = 0
    lazy_skips: int = 0

    @property
    def accounts(self) -> list[str]:
        return [step.account_id for step in self.steps]


def issue_minute(rank: int, complaint_minute: int) -> int:
    """When the `rank`-th instruction (0-based) actually takes effect.

    Instructions go out in parallel batches, each taking a fixed time to reach
    the holding bank. This is why the ordering of the plan is a decision rather
    than a presentation detail.
    """
    batch = rank // max(settings.freeze_parallel_dispatch, 1)
    delay = (batch + 1) * settings.freeze_issue_latency_minutes
    return complaint_minute + int(math.ceil(delay))


def innocence_cost(p_mule: float, activity_weight: float, action: str) -> float:
    """What it costs to be wrong about this account.

    `w_innocence * (1 - p_mule) * activity_weight * harm(action)`.

    `activity_weight` is higher for accounts that look like someone's actual
    financial life -- long history, regular salary credits, many counterparties.
    Freezing a dormant account nobody uses is an inconvenience; freezing the
    account a family's salary lands in is real harm, and the objective has to
    know the difference.
    """
    # The score is capped before costing: see `score_confidence_ceiling`. No
    # model output justifies treating a freeze on a real person as free.
    confidence = min(p_mule, settings.score_confidence_ceiling)
    return (
        settings.w_innocence
        * max(0.0, 1.0 - confidence)
        * max(activity_weight, 0.05)
        * settings.action_harm_weight[action]
    )


def allowed_actions(p_mule: float) -> tuple[str, ...]:
    """Which actions are proportionate for an account at this suspicion level.

    Below the lowest threshold nothing is proportionate and the account is not
    a candidate at all. This is the graded response being real: a full freeze
    is simply unavailable for an account we only mildly suspect, whatever it
    would do for the recovery figure.
    """
    if p_mule >= settings.action_full_freeze_threshold:
        return ACTIONS
    if p_mule >= settings.action_outbound_hold_threshold:
        return ("outbound_hold", "step_up_verification")
    if p_mule >= settings.action_step_up_threshold:
        return ("step_up_verification",)
    return ()


def solve(
    rollouts: RolloutSet,
    p_mule: dict[str, float],
    activity_weight: dict[str, float],
    budget_k: int | None = None,
    innocence_budget: float | None = None,
) -> FreezePlan:
    """Greedy freeze-frontier solver with CELF lazy evaluation."""
    started = time.perf_counter()
    k = budget_k if budget_k is not None else settings.default_budget_k
    budget = (
        innocence_budget
        if innocence_budget is not None
        else settings.default_innocence_budget
    )

    plan = FreezePlan()
    if not rollouts.particles or k <= 0:
        plan.projected_leak_inr = rollouts.expected_leak
        plan.solve_ms = (time.perf_counter() - started) * 1000
        return plan

    blocking = rollouts.blocking_index()
    values = rollouts.values

    # `survival[i]` is the probability parcel i still gets out, given the
    # freezes chosen so far. Every marginal gain is computed against it.
    survival = np.ones(len(rollouts.particles), dtype=np.float64)
    escapes = np.array(
        [1.0 if p.exited else 0.0 for p in rollouts.particles], dtype=np.float64
    )

    candidates = _build_candidates(blocking, p_mule, values, escapes)
    if not candidates:
        plan.projected_leak_inr = rollouts.expected_leak
        plan.solve_ms = (time.perf_counter() - started) * 1000
        return plan

    def run(limit: int, by_ratio: bool) -> FreezePlan:
        return _greedy(
            candidates,
            blocking,
            values,
            escapes,
            survival.copy(),
            rollouts,
            p_mule,
            activity_weight,
            limit,
            budget,
            by_ratio=by_ratio,
        )

    # Three passes, best one wins. This is not belt-and-braces; each covers a
    # case the others get wrong.
    #
    #  * value-greedy carries the (1 - 1/e) guarantee under the cardinality
    #    budget, and is what should win when the innocence budget is slack.
    #  * ratio-greedy is what handles a binding innocence budget, spending the
    #    scarce resource where it buys the most.
    #  * best-single-item is the standard companion to ratio-greedy; together
    #    they restore a (1/2)(1 - 1/e) guarantee for the knapsack form.
    #
    # Running only ratio-greedy has a nasty failure mode. When the budget does
    # not bind, every action is nearly free, and dividing by a near-zero cost
    # makes the *cheapest* action look best -- so the solver issues a
    # step-up verification on an account it is certain about, trading away half
    # the effectiveness to save a budget it was never going to exhaust.
    value_plan = run(k, by_ratio=False)
    ratio_plan = run(k, by_ratio=True)
    single_plan = run(1, by_ratio=False)

    # Compare on the objective actually optimised, not on one of its two
    # components -- otherwise a safeguard can swap in a worse plan.
    def objective(candidate: FreezePlan) -> float:
        return (
            candidate.projected_recovery_inr
            + settings.parked_money_weight * candidate.projected_secured_inr
        )

    best = max((value_plan, ratio_plan, single_plan), key=objective)
    best.solve_ms = (time.perf_counter() - started) * 1000
    log.debug(
        "solved %s: %d freezes, %.0f recovered, %.0f ms",
        rollouts.incident_id,
        len(best.steps),
        best.projected_recovery_inr,
        best.solve_ms,
    )
    return best


def _build_candidates(
    blocking: dict[str, dict[int, int]],
    p_mule: dict[str, float],
    values: np.ndarray,
    escapes: np.ndarray,
) -> list[FreezeOption]:
    """Every (account, action) pair worth considering.

    An account is only a candidate if it sits on the path of money that would
    otherwise escape *and* its suspicion level makes some action proportionate.
    """
    weights = escapes + settings.parked_money_weight

    options: list[FreezeOption] = []
    for account, particles in blocking.items():
        if not particles:
            continue
        at_stake = float(sum(values[i] * weights[i] for i in particles))
        if at_stake <= 0.0:
            continue
        for action in allowed_actions(p_mule.get(account, 0.0)):
            options.append(FreezeOption(account_id=account, action=action))
    return options


def _greedy(
    candidates: list[FreezeOption],
    blocking: dict[str, dict[int, int]],
    values: np.ndarray,
    escapes: np.ndarray,
    survival: np.ndarray,
    rollouts: RolloutSet,
    p_mule: dict[str, float],
    activity_weight: dict[str, float],
    k: int,
    budget: float,
    by_ratio: bool,
) -> FreezePlan:
    """One greedy pass. `by_ratio` picks by gain-per-cost, else by raw gain."""
    plan = FreezePlan()
    n_rollouts = max(rollouts.n_rollouts, 1)

    # Intercepting money that would have escaped is the objective; securing
    # money that was going to sit still is worth a fraction of that. Both terms
    # are coverage functions, so the sum stays submodular.
    weights = escapes + settings.parked_money_weight

    def gain_of(option: FreezeOption, at_minute: int) -> float:
        """Expected rupees saved by this action, landing at `at_minute`."""
        particles = blocking.get(option.account_id)
        if not particles:
            return 0.0
        effectiveness = option.effectiveness
        total = 0.0
        for particle, departs in particles.items():
            # The instruction only helps if it lands before the money leaves.
            if departs < at_minute:
                continue
            total += (
                values[particle] * weights[particle] * survival[particle] * effectiveness
            )
        return total / n_rollouts

    def cost_of(option: FreezeOption) -> float:
        return innocence_cost(
            p_mule.get(option.account_id, 0.0),
            activity_weight.get(option.account_id, 1.0),
            option.action,
        )

    # CELF: a max-heap of optimistic gains, refreshed only when a candidate
    # reaches the top with a stale value.
    first_minute = issue_minute(0, rollouts.complaint_minute)
    heap: list[tuple[float, int, int]] = []
    for position, option in enumerate(candidates):
        gain = gain_of(option, first_minute)
        # Counted here, not after the filter: the evaluation has already been
        # paid for by the call above, and a candidate rejected for zero gain
        # cost exactly as much to reject as one that was kept.
        plan.evaluations += 1
        if gain <= 0.0:
            continue
        cost = cost_of(option)
        key = gain / max(cost, 1e-6) if by_ratio else gain
        heap.append((-key, position, -1))
    heapq.heapify(heap)

    chosen: set[str] = set()
    spent = 0.0

    while heap and len(plan.steps) < k:
        rank = len(plan.steps)
        at_minute = issue_minute(rank, rollouts.complaint_minute)

        neg_key, position, stamp = heapq.heappop(heap)
        option = candidates[position]

        if option.account_id in chosen:
            continue

        cost = cost_of(option)
        if spent + cost > budget:
            continue  # cannot afford it; other candidates may still fit

        # Recompute only when the cached value is stale for this step.
        if stamp != rank:
            gain = gain_of(option, at_minute)
            plan.evaluations += 1
            if gain <= 0.0:
                continue
            key = gain / max(cost, 1e-6) if by_ratio else gain
            heapq.heappush(heap, (-key, position, rank))
            plan.lazy_skips += 1
            continue

        gain = -neg_key * (max(cost, 1e-6) if by_ratio else 1.0)
        if gain <= 0.0:
            break

        # Commit: this money is now covered, so every later gain shrinks.
        particles = blocking[option.account_id]
        for particle, departs in particles.items():
            if departs >= at_minute:
                survival[particle] *= 1.0 - option.effectiveness

        chosen.add(option.account_id)
        spent += cost
        plan.steps.append(
            FreezeStep(
                rank=rank + 1,
                account_id=option.account_id,
                action=option.action,
                issue_at_minute=at_minute,
                marginal_recovery_inr=round(gain, 2),
                p_mule=round(p_mule.get(option.account_id, 0.0), 4),
                innocence_cost=round(cost, 4),
                effectiveness=option.effectiveness,
            )
        )

    # Report the two quantities separately and honestly. `survival` is the
    # probability a parcel was *not* intercepted, so leakage is what escapes
    # uncaught and secured money is everything caught.
    leaked = float((values * escapes * survival).sum()) / n_rollouts
    secured = float((values * (1.0 - survival)).sum()) / n_rollouts

    plan.projected_leak_inr = round(leaked, 2)
    plan.projected_secured_inr = round(secured, 2)
    plan.projected_recovery_inr = round(
        max(0.0, rollouts.expected_leak - leaked), 2
    )
    plan.total_innocence_cost = round(spent, 4)
    plan.innocent_accounts_frozen_expected = round(
        sum(1.0 - p_mule.get(s.account_id, 0.0) for s in plan.steps), 3
    )
    return plan
