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
from app.interdict.policies import IncidentContext, build_context

log = logging.getLogger(__name__)

_lock = threading.Lock()
_contexts: "OrderedDict[str, IncidentContext]" = OrderedDict()
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


def context_for_scenario(scenario_id: str) -> IncidentContext:
    return context_for(scenario_incident(scenario_id))


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
