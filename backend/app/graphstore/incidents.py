"""The incident: one fraud complaint, and everything derived from it.

An *episode* is something the syndicate did -- a run of money through a ring.
An *incident* is an episode plus a complaint delay: the moment a victim walks
into a police station and the clock starts. The same episode reported at eleven
minutes and at six hours is two completely different problems, which is why the
delay belongs in the incident rather than in the data.

Everything downstream shares this one definition, so a number quoted in the
Evaluation tab means the same thing as a number quoted on the console.

**The train / hold-out split.** Rings in `settings.holdout_ring_ids` are kept
out of detector training entirely, one per typology. RING-01 is among them, and
RING-01 is scenario S1 -- the stage demo. The demo therefore runs against a ring
the detector has never seen. Any other arrangement makes the live numbers
meaningless, and it is the first thing a good judge will ask about.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np
import polars as pl

from app.config import settings
from app.graphstore.build import Dataset, load_dataset
from app.simulator.scenarios import SCENARIOS_BY_ID

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Incident:
    """One fraud complaint, ready to be planned against."""

    incident_id: str
    episode_id: str
    ring_id: str
    typology: str
    victim_account: str
    amount_inr: float
    incident_time: datetime
    complaint_delay_minutes: int
    #: Set only for the six demo scenarios; empty for benchmark incidents.
    scenario_id: str = ""

    @property
    def complaint_time(self) -> datetime:
        return self.incident_time + timedelta(minutes=self.complaint_delay_minutes)

    @property
    def horizon_end(self) -> datetime:
        return self.incident_time + timedelta(hours=settings.incident_horizon_hours)

    def with_delay(self, minutes: int) -> "Incident":
        """The same episode, reported after a different delay."""
        return Incident(
            incident_id=f"{self.episode_id}@{minutes}",
            episode_id=self.episode_id,
            ring_id=self.ring_id,
            typology=self.typology,
            victim_account=self.victim_account,
            amount_inr=self.amount_inr,
            incident_time=self.incident_time,
            complaint_delay_minutes=minutes,
            scenario_id=self.scenario_id,
        )


def is_holdout(ring_id: str) -> bool:
    return ring_id in set(settings.holdout_ring_ids)


def scenario_incident(scenario_id: str) -> Incident:
    """The incident behind one of the six seeded demo scenarios."""
    scenario = SCENARIOS_BY_ID.get(scenario_id)
    if scenario is None:
        raise KeyError(f"Unknown scenario {scenario_id!r}")

    dataset = load_dataset()
    row = dataset.episodes.filter(pl.col("scenario_id") == scenario_id)
    if row.height == 0:
        raise KeyError(f"No episode recorded for scenario {scenario_id!r}")

    record = row.row(0, named=True)
    return Incident(
        incident_id=scenario_id,
        episode_id=str(record["episode_id"]),
        ring_id=str(record["ring_id"]),
        typology=str(record["typology"]),
        victim_account=scenario.victim_account,
        amount_inr=scenario.amount_inr,
        incident_time=scenario.incident_time,
        complaint_delay_minutes=scenario.complaint_delay_minutes,
        scenario_id=scenario_id,
    )


def episodes_for(
    holdout: bool | None = None, dataset: Dataset | None = None
) -> list[Incident]:
    """Every recorded episode, with its natural complaint delay.

    `holdout=True` returns only episodes from held-out rings, `False` only
    training rings, `None` everything.
    """
    ds = dataset if dataset is not None else load_dataset()
    held = set(settings.holdout_ring_ids)

    rows = ds.episodes
    if holdout is True:
        rows = rows.filter(pl.col("ring_id").is_in(held))
    elif holdout is False:
        rows = rows.filter(~pl.col("ring_id").is_in(held))

    out: list[Incident] = []
    for record in rows.iter_rows(named=True):
        scenario_id = str(record["scenario_id"])
        scenario = SCENARIOS_BY_ID.get(scenario_id)
        delay = (
            scenario.complaint_delay_minutes
            if scenario is not None
            else _default_delay(str(record["episode_id"]))
        )
        out.append(
            Incident(
                incident_id=scenario_id or str(record["episode_id"]),
                episode_id=str(record["episode_id"]),
                ring_id=str(record["ring_id"]),
                typology=str(record["typology"]),
                victim_account=str(record["victim_account"]),
                amount_inr=float(record["amount_inr"]),
                incident_time=record["start_time"],
                complaint_delay_minutes=delay,
                scenario_id=scenario_id,
            )
        )
    return out


def _default_delay(episode_id: str) -> int:
    """A plausible complaint delay, derived deterministically from the id.

    Reporting delay is heavily right-skewed: a minority notice within minutes,
    most take an hour or more, and a long tail reports the next morning. A
    log-normal reproduces that shape. Deriving the draw from the episode id
    rather than a shared stream means an episode's delay does not change when
    unrelated code starts consuming randomness.
    """
    seed = int.from_bytes(episode_id.encode()[-8:], "little", signed=False)
    rng = np.random.default_rng(seed % (2**32))
    minutes = float(rng.lognormal(mean=3.9, sigma=1.0))
    return int(np.clip(minutes, 4, settings.incident_horizon_hours * 60 - 30))


@lru_cache(maxsize=1)
def benchmark_incidents() -> tuple[Incident, ...]:
    """The fixed set of incidents the published benchmark runs over.

    Held-out rings only, so no incident here shares a ring with anything the
    detector trained on. Episodes are sampled with several complaint delays
    each, because delay is the single most important variable in the outcome
    and a benchmark that fixed it would hide that.
    """
    pool = episodes_for(holdout=True)
    if not pool:
        raise RuntimeError("no held-out episodes; check holdout_ring_ids")

    pool = sorted(pool, key=lambda incident: incident.episode_id)
    rng = np.random.default_rng(settings.master_seed)

    target = settings.n_benchmark_incidents
    out: list[Incident] = []
    round_index = 0
    while len(out) < target:
        for incident in pool:
            if len(out) >= target:
                break
            delay = (
                incident.complaint_delay_minutes
                if round_index == 0
                else int(
                    np.clip(
                        rng.lognormal(mean=3.9, sigma=1.0),
                        4,
                        settings.incident_horizon_hours * 60 - 30,
                    )
                )
            )
            out.append(incident.with_delay(delay))
        round_index += 1

    log.info(
        "benchmark: %d incidents across %d held-out episodes",
        len(out),
        len(pool),
    )
    return tuple(out)
