"""WebSocket replay: the incident playing out, minute by minute.

    WS /ws/replay/{scenario_id}?policy=...&budget_k=...&innocence_budget=...

The entire demo runs from this one stream. Each frame carries a simulated
minute for *both* timelines -- what happens with no intervention, and what
happens under the plan -- so the split comparison on the console is two views
of one computation rather than two computations that might disagree.

The server owns the clock. Frames are streamed at `replay_fps`, and the client
animates between them but never invents them. A client-side timer would drift
away from the data it is supposed to be showing, and the moment it does, the
rupee counters stop matching the graph.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api import session
from app.config import settings
from app.graphstore.build import DatasetMissingError
from app.interdict.greedy import FreezePlan
from app.interdict.policies import POLICIES, plan_for
from app.interdict.replay import MinuteFrame, replay

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/replay/{scenario_id}")
async def replay_stream(
    websocket: WebSocket,
    scenario_id: str,
    policy: str = Query(default="chakravyuh_greedy"),
    budget_k: int = Query(default=settings.default_budget_k, ge=0, le=200),
    innocence_budget: float = Query(
        default=settings.default_innocence_budget, ge=0.0, le=50.0
    ),
    adaptive_adversary: bool = Query(default=False),
    fps: int = Query(default=settings.replay_fps, ge=1, le=60),
) -> None:
    await websocket.accept()

    if policy not in POLICIES:
        await websocket.send_json(
            {"type": "error", "detail": f"Unknown policy {policy!r}"}
        )
        await websocket.close()
        return

    try:
        context = session.context_for_scenario(scenario_id)
    except DatasetMissingError as exc:
        await websocket.send_json({"type": "error", "detail": str(exc)})
        await websocket.close()
        return
    except KeyError:
        await websocket.send_json(
            {"type": "error", "detail": f"Unknown scenario {scenario_id}"}
        )
        await websocket.close()
        return

    horizon = settings.incident_horizon_hours * 60
    mules = session.dataset().mule_ids

    plan = plan_for(policy, context, budget_k, innocence_budget)
    baseline_plan = plan_for("named_account_only", context, budget_k, innocence_budget)

    # The adversary setting has to reach the replay, not just the planner. This
    # stream drives the "where the money ended up" panel, so if the checkbox
    # only changed `POST /api/interdict` it would move a number on one screen
    # and leave the animation next to it telling a different story. Matches
    # `interdict.py`, deliberately: same setting, same rate, both timelines.
    reroute = settings.adversary_reroute_prob if adaptive_adversary else 0.0

    # Both timelines are computed up front. The stream is then a pure playback,
    # which is what makes the demo identical every run -- and what lets the
    # client scrub backwards without recomputing anything.
    treated = replay(
        context.state, plan, horizon, mules, session.index(),
        reroute_prob=reroute, collect_frames=True,
    )
    baseline = replay(
        context.state, baseline_plan, horizon, mules, session.index(),
        reroute_prob=reroute, collect_frames=True,
    )

    await websocket.send_json(
        {
            "type": "header",
            "scenario_id": scenario_id,
            "policy": policy,
            "amount_inr": context.incident.amount_inr,
            "complaint_minute": context.rollouts.complaint_minute,
            "horizon_minutes": horizon,
            "fps": fps,
            "plan_size": len(plan.steps),
            "already_gone_inr": treated.already_gone_inr,
            "final": {
                "chakravyuh": _totals(treated),
                "baseline": _totals(baseline),
            },
        }
    )

    interval = 1.0 / fps
    try:
        for minute in range(horizon + 1):
            await websocket.send_json(
                _frame(
                    minute,
                    treated.frames[minute] if minute < len(treated.frames) else None,
                    baseline.frames[minute] if minute < len(baseline.frames) else None,
                    context.incident.amount_inr,
                )
            )
            await asyncio.sleep(interval)

        await websocket.send_json({"type": "end", "minute": horizon})
    except WebSocketDisconnect:
        log.debug("replay client disconnected from %s", scenario_id)
    except (RuntimeError, ConnectionError) as exc:  # pragma: no cover
        log.debug("replay stream closed: %s", exc)


def _totals(result) -> dict[str, object]:
    return {
        "leaked_inr": result.leaked_inr,
        "secured_inr": result.recovered_inr,
        "residual_inr": result.residual_inr,
        "innocent_frozen": result.innocent_frozen,
        "mules_frozen": result.mules_frozen,
        "frozen": len(result.frozen_accounts),
    }


def _frame(
    minute: int,
    treated: MinuteFrame | None,
    baseline: MinuteFrame | None,
    amount_inr: float,
) -> dict[str, object]:
    """One streamed frame, in the contract the console consumes.

    The top-level figures are Chakravyuh's, so the documented frame shape is
    preserved; `baseline` rides alongside so the split comparison never has to
    ask for a second stream and risk the two drifting apart.
    """
    flows = treated.flows if treated else []
    frozen = treated.frozen if treated else []

    return {
        "type": "frame",
        "minute": minute,
        "flows": flows,
        "frozen": frozen,
        "recovered_inr": treated.recovered_inr if treated else 0.0,
        "leaked_inr": treated.leaked_inr if treated else 0.0,
        "at_risk_inr": treated.at_risk_inr if treated else amount_inr,
        "frontier_accounts": frozen[-6:],
        "baseline": {
            "recovered_inr": baseline.recovered_inr if baseline else 0.0,
            "leaked_inr": baseline.leaked_inr if baseline else 0.0,
            "at_risk_inr": baseline.at_risk_inr if baseline else amount_inr,
            "frozen": baseline.frozen if baseline else [],
        },
    }
