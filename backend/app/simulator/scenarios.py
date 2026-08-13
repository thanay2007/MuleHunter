"""The six fixed, seeded incidents that drive the demo and the API.

Each scenario is a real, documented Indian fraud pattern. The victim accounts
are reserved slots at the head of the account table (AC000000..AC000005) so
that a scenario's victim is known at import time yet still carries the district
and archetype the story requires -- `population.build_accounts` reads these
records and stamps those attributes onto the reserved rows.

S1 is the stage demo. Everything about it is tuned for legibility: a large
round-ish amount, a complaint delay inside the golden hour, and a fan-out ring
deep enough that freezing only the named account visibly fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Ring identifiers are assigned deterministically by typology block:
#   RING-01..03 fanout, RING-04..06 chain_burst,
#   RING-07..09 structuring, RING-10..12 crypto_exit
RING_TYPOLOGY_ORDER: tuple[str, ...] = (
    "fanout",
    "chain_burst",
    "structuring",
    "crypto_exit",
)
RINGS_PER_TYPOLOGY: int = 3


def ring_id_for(typology: str, index: int) -> str:
    """Ring id for the `index`-th ring (0-based) of a given typology."""
    block = RING_TYPOLOGY_ORDER.index(typology)
    return f"RING-{block * RINGS_PER_TYPOLOGY + index + 1:02d}"


@dataclass(frozen=True)
class Scenario:
    """A seeded fraud incident."""

    scenario_id: str
    name: str
    summary: str
    victim_account: str
    victim_district: str
    victim_archetype: str
    amount_inr: float
    complaint_delay_minutes: int
    ring_id: str
    ring_typology: str
    incident_time: datetime
    seed: int
    # S5 launders through two rings simultaneously.
    secondary_ring_id: str | None = None

    @property
    def complaint_time(self) -> datetime:
        """When the victim actually reports. Nothing can be frozen before this."""
        from datetime import timedelta

        return self.incident_time + timedelta(minutes=self.complaint_delay_minutes)


_INCIDENT_DAY = "2026-08-10"


def _at(clock: str) -> datetime:
    return datetime.fromisoformat(f"{_INCIDENT_DAY}T{clock}")


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        scenario_id="S1",
        name="Digital arrest — retired teacher, Pune",
        summary=(
            "Caller impersonating CBI holds the victim on video for four hours and "
            "coerces a transfer to a 'verification account'."
        ),
        victim_account="AC000000",
        victim_district="Pune",
        victim_archetype="salaried",
        amount_inr=1_500_000.0,
        complaint_delay_minutes=42,
        ring_id=ring_id_for("fanout", 0),
        ring_typology="fanout",
        incident_time=_at("11:14:00"),
        seed=101,
    ),
    Scenario(
        scenario_id="S2",
        name="Investment scam — Telegram group, Surat",
        summary=(
            "Victim is walked through a fake trading dashboard showing paper gains, "
            "then asked to deposit again to 'unlock withdrawal'."
        ),
        victim_account="AC000001",
        victim_district="Surat",
        victim_archetype="small_merchant",
        amount_inr=850_000.0,
        complaint_delay_minutes=360,
        ring_id=ring_id_for("structuring", 0),
        ring_typology="structuring",
        incident_time=_at("15:40:00"),
        seed=102,
    ),
    Scenario(
        scenario_id="S3",
        name="UPI collect fraud — student, Patna",
        summary=(
            "Fake marketplace buyer sends a collect request disguised as a payment; "
            "victim approves it and debits their own account."
        ),
        victim_account="AC000002",
        victim_district="Patna",
        victim_archetype="student",
        amount_inr=62_000.0,
        complaint_delay_minutes=11,
        ring_id=ring_id_for("chain_burst", 0),
        ring_typology="chain_burst",
        incident_time=_at("19:05:00"),
        seed=103,
    ),
    Scenario(
        scenario_id="S4",
        name="Task scam — homemaker, Nagpur",
        summary=(
            "Victim completes paid 'review tasks', receives small payouts, then "
            "deposits a large sum for a 'premium task set'."
        ),
        victim_account="AC000003",
        victim_district="Nagpur",
        victim_archetype="homemaker",
        amount_inr=320_000.0,
        complaint_delay_minutes=120,
        ring_id=ring_id_for("crypto_exit", 0),
        ring_typology="crypto_exit",
        incident_time=_at("13:22:00"),
        seed=104,
    ),
    Scenario(
        scenario_id="S5",
        name="Deepfake CEO transfer — SME, Ahmedabad",
        summary=(
            "Finance staff join a video call with a synthesised company director "
            "and are instructed to release an urgent vendor payment."
        ),
        victim_account="AC000004",
        victim_district="Ahmedabad",
        victim_archetype="hnw",
        amount_inr=4_700_000.0,
        complaint_delay_minutes=25,
        ring_id=ring_id_for("fanout", 1),
        ring_typology="fanout",
        incident_time=_at("10:47:00"),
        seed=105,
        secondary_ring_id=ring_id_for("fanout", 2),
    ),
    Scenario(
        scenario_id="S6",
        name="Loan app extortion — gig worker, Delhi",
        summary=(
            "Predatory lending app harvests contacts and extorts repayment far "
            "beyond the principal under threat of morphed images."
        ),
        victim_account="AC000005",
        victim_district="New Delhi",
        victim_archetype="student",
        amount_inr=110_000.0,
        complaint_delay_minutes=90,
        ring_id=ring_id_for("structuring", 1),
        ring_typology="structuring",
        incident_time=_at("21:30:00"),
        seed=106,
    ),
)

SCENARIOS_BY_ID: dict[str, Scenario] = {s.scenario_id: s for s in SCENARIOS}

#: Account slots reserved for scenario victims, in table order.
RESERVED_VICTIM_SLOTS: int = len(SCENARIOS)