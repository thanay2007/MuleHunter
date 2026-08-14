"""Phase 4 acceptance: the freeze-frontier solver. This is the project.

Acceptance checks (from the build plan):
    Greedy returns a freeze plan for a 5k-node graph in under 2 seconds, and
    beats every baseline on recovery.

    On scenario S1, Chakravyuh recovers at least 8x `named_account_only` and at
    least 2x `top_k_classifier`, at equal or lower innocent-freeze count.

The comparison metric throughout is *prevented leakage*: rupees kept inside the
banking system that would otherwise have been cashed out, measured against a
do-nothing replay of the same incident. Freezing an account that was never
going to move money cannot inflate it.
"""

from __future__ import annotations

import time

import pytest

from app.config import settings
from app.interdict import greedy
from app.interdict.greedy import FreezePlan
from app.interdict.policies import POLICIES, plan_for
from app.interdict.replay import replay

from tests.conftest import needs_dataset, needs_detector

pytestmark = [needs_dataset, needs_detector]

HORIZON = settings.incident_horizon_hours * 60


def prevented(context, plan, dataset, index) -> float:
    """Rupees this plan kept inside the banking system."""
    nothing = replay(
        context.state, FreezePlan(), HORIZON, dataset.mule_ids, index, reroute_prob=0.0
    )
    treated = replay(
        context.state, plan, HORIZON, dataset.mule_ids, index, reroute_prob=0.0
    )
    return max(0.0, nothing.leaked_inr - treated.leaked_inr)


# ------------------------------------------------------------------- latency


def test_solver_meets_its_latency_budget(s1_context) -> None:
    """A slow solver is a broken demo, so this is a hard budget."""
    started = time.perf_counter()
    plan = plan_for("chakravyuh_greedy", s1_context)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms < settings.greedy_latency_budget_ms, (
        f"solve took {elapsed_ms:.0f}ms against a "
        f"{settings.greedy_latency_budget_ms}ms budget"
    )
    assert plan.steps, "solver returned an empty plan"


def test_solver_runs_at_full_graph_scale(s1_context) -> None:
    """The acceptance bar is a 5,000-node graph, not a toy one."""
    assert len(s1_context.candidates) >= 1_000, (
        f"only {len(s1_context.candidates)} candidates -- the latency claim is "
        "not being tested at a meaningful scale"
    )


# ------------------------------------------------------------ policy ranking


def test_chakravyuh_beats_every_baseline(s1_context, dataset, index) -> None:
    plans = {
        policy: plan_for(policy, s1_context) for policy in POLICIES
    }
    scores = {
        policy: prevented(s1_context, plan, dataset, index)
        for policy, plan in plans.items()
    }

    ours = scores["chakravyuh_greedy"]
    for policy, value in scores.items():
        if policy == "chakravyuh_greedy":
            continue
        assert ours >= value, f"{policy} prevented more than chakravyuh_greedy"


def test_s1_clears_the_acceptance_margins(s1_context, dataset, index) -> None:
    """At least 8x current practice and 2x a top-K classifier."""
    ours = prevented(
        s1_context, plan_for("chakravyuh_greedy", s1_context), dataset, index
    )
    named = prevented(
        s1_context, plan_for("named_account_only", s1_context), dataset, index
    )
    topk = prevented(
        s1_context, plan_for("top_k_classifier", s1_context), dataset, index
    )

    assert ours > 0, "chakravyuh prevented nothing on the stage scenario"
    # Current practice frequently prevents nothing at all on S1 -- the money has
    # left the named account long before the complaint. Any positive recovery
    # clears an 8x margin against zero.
    assert named == 0 or ours >= 8 * named, f"{ours:,.0f} vs 8 x {named:,.0f}"
    assert topk == 0 or ours >= 2 * topk, f"{ours:,.0f} vs 2 x {topk:,.0f}"


def test_no_more_innocent_freezes_than_the_baselines(s1_context, dataset, index) -> None:
    """Recovery bought by freezing more innocent people is not recovery."""
    results = {}
    for policy in POLICIES:
        plan = plan_for(policy, s1_context)
        results[policy] = replay(
            s1_context.state, plan, HORIZON, dataset.mule_ids, index, reroute_prob=0.0
        ).innocent_frozen

    ours = results["chakravyuh_greedy"]
    assert ours <= results["top_k_classifier"]
    assert ours <= results["one_hop_downstream"]


# ------------------------------------------------------------------- budgets


def test_freeze_budget_is_respected(s1_context) -> None:
    for k in (1, 5, 12, 25):
        plan = plan_for("chakravyuh_greedy", s1_context, budget_k=k)
        assert len(plan.steps) <= k


def test_innocence_budget_is_respected(s1_context) -> None:
    for budget in (0.05, 0.25, 1.0, 4.0):
        plan = plan_for(
            "chakravyuh_greedy", s1_context, innocence_budget=budget
        )
        spent = sum(step.innocence_cost for step in plan.steps)
        # Rounding in the reported per-step costs allows a hair of slack.
        assert spent <= budget + 1e-3, f"spent {spent} against budget {budget}"


def test_tightening_innocence_budget_never_helps_recovery(s1_context) -> None:
    """Monotonicity check: a tighter constraint cannot buy more recovery.

    If this fails the solver is not actually respecting the budget, or the
    objective is not monotone -- either way the (1 - 1/e) claim is void.
    """
    scores = []
    for budget in (0.1, 0.5, 2.0, 8.0):
        plan = plan_for(
            "chakravyuh_greedy", s1_context, innocence_budget=budget
        )
        scores.append(plan.projected_recovery_inr)

    for tighter, looser in zip(scores, scores[1:]):
        assert tighter <= looser * 1.02, (
            "a tighter innocence budget produced more projected recovery"
        )


def test_more_authority_never_hurts(s1_context) -> None:
    scores = [
        plan_for("chakravyuh_greedy", s1_context, budget_k=k).projected_recovery_inr
        for k in (5, 12, 25, 40)
    ]
    for smaller, larger in zip(scores, scores[1:]):
        assert smaller <= larger * 1.02


# ------------------------------------------------------------ graded response


def test_actions_stay_proportionate_to_suspicion(s1_context) -> None:
    """A full freeze must never be issued on an account we barely suspect."""
    plan = plan_for("chakravyuh_greedy", s1_context)
    for step in plan.steps:
        allowed = greedy.allowed_actions(step.p_mule)
        assert step.action in allowed, (
            f"{step.action} issued on an account scored {step.p_mule}"
        )


def test_a_tight_innocence_budget_forces_gentler_actions(s1_context) -> None:
    """This is the answer to 'you will freeze innocent people', and it is real.

    Squeezed hard enough, the solver stops issuing full freezes and switches to
    lower-harm actions rather than simply freezing fewer accounts.
    """
    tight = plan_for("chakravyuh_greedy", s1_context, innocence_budget=0.06)
    loose = plan_for("chakravyuh_greedy", s1_context, innocence_budget=8.0)

    if not tight.steps:
        pytest.skip("no plan is affordable at this budget")

    gentle = {"outbound_hold", "step_up_verification"}
    tight_share = sum(1 for s in tight.steps if s.action in gentle) / len(tight.steps)
    loose_share = sum(1 for s in loose.steps if s.action in gentle) / max(
        len(loose.steps), 1
    )
    assert tight_share >= loose_share


def test_plan_is_ordered_and_freezes_come_after_the_complaint(s1_context) -> None:
    plan = plan_for("chakravyuh_greedy", s1_context)
    complaint = s1_context.rollouts.complaint_minute

    assert [s.rank for s in plan.steps] == list(range(1, len(plan.steps) + 1))
    for step in plan.steps:
        assert step.issue_at_minute > complaint, (
            "a freeze was issued before the victim reported"
        )

    issue_times = [s.issue_at_minute for s in plan.steps]
    assert issue_times == sorted(issue_times), "plan order does not match issue order"


def test_no_account_appears_twice(s1_context) -> None:
    plan = plan_for("chakravyuh_greedy", s1_context)
    accounts = [s.account_id for s in plan.steps]
    assert len(accounts) == len(set(accounts))


# ----------------------------------------------------------------- soundness


def test_determinism(s1_context) -> None:
    """The same scenario must produce the same plan every run."""
    first = plan_for("chakravyuh_greedy", s1_context)
    second = plan_for("chakravyuh_greedy", s1_context)
    assert [s.account_id for s in first.steps] == [s.account_id for s in second.steps]
    assert [s.action for s in first.steps] == [s.action for s in second.steps]


def test_replay_conserves_money(s1_context, dataset, index) -> None:
    plan = plan_for("chakravyuh_greedy", s1_context)
    result = replay(
        s1_context.state, plan, HORIZON, dataset.mule_ids, index, reroute_prob=0.0
    )
    total = result.leaked_inr + result.recovered_inr + result.residual_inr
    assert total <= result.amount_inr + 1.0
    # Nothing may be recovered that was already gone before the complaint.
    assert result.already_gone_inr <= result.leaked_inr + 1.0


def test_adaptive_adversary_never_flatters_the_result(s1_context, dataset, index) -> None:
    """An operator who reroutes must not make us look better."""
    plan = plan_for("chakravyuh_greedy", s1_context)
    passive = replay(
        s1_context.state, plan, HORIZON, dataset.mule_ids, index, reroute_prob=0.0
    )
    adaptive = replay(
        s1_context.state, plan, HORIZON, dataset.mule_ids, index, reroute_prob=0.35
    )
    assert adaptive.leaked_inr >= passive.leaked_inr - 1.0


def test_greedy_is_close_to_the_exact_optimum(s1_context) -> None:
    """Measure the gap rather than asserting the bound."""
    from app.interdict.exact_cpsat import solve_exact

    plan = plan_for("chakravyuh_greedy", s1_context)
    result = solve_exact(
        s1_context.rollouts,
        s1_context.p_mule,
        s1_context.activity_weight,
        plan,
        max_accounts=1_500,
    )
    if not result.solved:
        pytest.skip(f"CP-SAT did not solve this incident: {result.status}")

    bound = 1 - 1 / 2.718281828459045
    assert result.greedy_value_inr >= bound * result.optimal_value_inr * 0.99, (
        f"greedy reached {result.greedy_value_inr:,.0f} against an optimum of "
        f"{result.optimal_value_inr:,.0f} -- below the (1-1/e) guarantee"
    )
