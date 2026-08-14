"""Shared per-incident state for the API.

Tracing, featurising, scoring and rolling out an incident costs a couple of
seconds. The console then asks about the same incident repeatedly -- a plan,
then a replay stream, then an account drawer, then a re-plan with a different
budget -- and every one of those needs identical inputs.

So contexts are built once and cached. Beyond the latency, this is what
guarantees the drawer's explanation refers to the same scored graph the plan
was built from. Rebuilding per request would leave the UI quietly explaining a
different computation from the one it displayed.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict

from app.config import settings
from app.detect.gbdt import Detector, load_detector
from app.graphstore.build import Dataset, load_dataset
from app.graphstore.incidents import Incident, scenario_incident
from app.graphstore.trace import TransactionIndex, transaction_index
from app.interdict.greedy import FreezePlan
from app.interdict.policies import IncidentContext, build_context, plan_for

log = logging.getLogger(__name__)

_lock = threading.Lock()
_contexts: "OrderedDict[str, IncidentContext]" = OrderedDict()
_plans: "OrderedDict[str, FreezePlan]" = OrderedDict()
#: Incidents filed through the intake form, addressable by id like a scenario.
_incidents: "OrderedDict[str, Incident]" = OrderedDict()
_detector: Detector | None = None
_detector_loaded = False


def detector() -> Detector | None:
    """The trained detector, loaded once. None if training has not been run."""
    global _detector, _detector_loaded
    if not _detector_loaded:
        with _lock:
            if not _detector_loaded:
                _detector = load_detector()
                _detector_loaded = True
                if _detector is None:
                    log.warning(
                        "no trained detector found -- falling back to the rules "
                        "tier. Run: python -m app.detect.train"
                    )
    return _detector


def dataset() -> Dataset:
    return load_dataset()


def index() -> TransactionIndex:
    return transaction_index()


def context_for(incident: Incident) -> IncidentContext:
    """Get or build the cached context for an incident."""
    key = f"{incident.incident_id}@{incident.complaint_delay_minutes}"

    with _lock:
        cached = _contexts.get(key)
        if cached is not None:
            _contexts.move_to_end(key)
            return cached

    # Built outside the lock: this takes seconds, and holding the lock would
    # serialise every other request behind it.
    built = build_context(incident, dataset(), index(), detector())

    with _lock:
        _contexts[key] = built
        _contexts.move_to_end(key)
        while len(_contexts) > settings.context_cache_size:
            _contexts.popitem(last=False)
    return built


def register_incident(incident: Incident) -> None:
    """Make an intake incident addressable like one of the six seeded ones.

    Everything downstream -- the graph, the plan, the replay socket, the freeze
    order -- looks incidents up by id. Registering here rather than threading a
    second kind of incident through those routes means a complaint typed into
    the intake form runs the *same* code path as S1, which is the whole point
    of having the form: it proves the six scenarios are not hardcoded theatre.
    """
    with _lock:
        _incidents[incident.incident_id] = incident
        _incidents.move_to_end(incident.incident_id)
        while len(_incidents) > settings.intake_cache_size:
            _incidents.popitem(last=False)


def incident_for(scenario_id: str) -> Incident:
    """A seeded scenario, or an incident filed through intake."""
    with _lock:
        filed = _incidents.get(scenario_id)
    if filed is not None:
        return filed
    return scenario_incident(scenario_id)


def context_for_scenario(scenario_id: str) -> IncidentContext:
    return context_for(incident_for(scenario_id))


def plan_for_scenario(
    scenario_id: str, policy: str, budget_k: int, innocence_budget: float
) -> FreezePlan:
    """The plan for these settings, solved once and then remembered.

    The freeze order and the console must quote the same plan -- same accounts,
    same order, same issue minutes -- or the document a bank receives disagrees
    with the screen it was approved on. Greedy is deterministic, so re-solving
    would in fact produce the same answer; caching makes that a guarantee
    rather than a property nobody re-checks, and keeps the order endpoint from
    spending a second of solve time to reprint something already on screen.
    """
    key = f"{scenario_id}|{policy}|{budget_k}|{innocence_budget}"

    with _lock:
        cached = _plans.get(key)
        if cached is not None:
            _plans.move_to_end(key)
            return cached

    built = plan_for(policy, context_for_scenario(scenario_id), budget_k, innocence_budget)

    with _lock:
        _plans[key] = built
        _plans.move_to_end(key)
        while len(_plans) > settings.plan_cache_size:
            _plans.popitem(last=False)
    return built


def warm(scenario_id: str = "S1") -> None:
    """Prepare everything the first click would otherwise pay for.

    Builds the DuckDB warehouse if it is missing and pre-computes the stage
    scenario's context. Neither is allowed to prevent the server starting: an
    API that refuses to boot because a derived file is stale is worse than one
    that is briefly slow.
    """
    from app.graphstore import warehouse

    try:
        warehouse.ensure_warehouse()
    except Exception as exc:  # noqa: BLE001 - warming must never block startup
        log.info("could not build the warehouse: %s", exc)

    try:
        context_for_scenario(scenario_id)
        log.info("warmed incident context for %s", scenario_id)
    except Exception as exc:  # noqa: BLE001
        log.info("could not warm %s: %s", scenario_id, exc)
