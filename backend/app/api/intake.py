"""Complaint intake: run the pipeline on an arbitrary incident.

    POST /api/intake

The six demo scenarios are seeded, which invites the fair question of whether
anything here generalises or whether the console is six hardcoded outcomes in a
trench coat. This endpoint answers it: give it any account in the dataset, any
amount, any pair of times, and it traces, featurises, scores, rolls out and
solves exactly as the seeded cases do.

It is deliberately not a second code path. It builds an `Incident` and hands it
to the same `session.context_for` every other route uses, so a plan produced
here is produced by the same machinery -- there is nothing to keep in sync and
nothing that could quietly diverge.

Validation is strict and the errors are specific, because the most likely use
of this form on stage is a judge typing an account number that does not exist,
and "unknown account" is a far better answer than a stack trace.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import polars as pl
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api import references, session
from app.config import settings
from app.graphstore.build import DatasetMissingError
from app.graphstore.incidents import Incident

log = logging.getLogger(__name__)
router = APIRouter()


class IntakeRequest(BaseModel):
    victim_account: str = Field(description="Must exist in the dataset.")
    amount_inr: float = Field(gt=0, le=100_000_000)
    #: When the money left. Must fall inside the simulated window.
    incident_time: datetime
    #: How long the victim took to report. The single most important variable
    #: in the whole system, which is why it is asked for directly.
    complaint_delay_minutes: int = Field(ge=0, le=24 * 60)
    channel: str = Field(default="UPI")


class IntakeResponse(BaseModel):
    """Enough for the console to switch to this incident and plan it."""

    incident_id: str
    #: Same derivation as a seeded case, so a filed complaint gets a real case
    #: number and can be issued as a freeze order like any other.
    case_id: str
    complaint_ref: str
    victim_account: str
    victim_bank: str
    victim_district: str
    amount_inr: float
    incident_time: datetime
    complaint_time: datetime
    complaint_delay_minutes: int
    channel: str

    #: What tracing actually found. If these are zero the complaint is real but
    #: the money never moved anywhere this dataset can see, and the console
    #: says so rather than presenting an empty plan as a result.
    accounts_traced: int
    candidates_considered: int
    tainted_still_inside_inr: float
    tainted_already_gone_inr: float


@router.post("/intake", response_model=IntakeResponse)
def intake(request: IntakeRequest) -> IntakeResponse:
    try:
        dataset = session.dataset()
    except DatasetMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    account = dataset.accounts.filter(
        pl.col("account_id") == request.victim_account
    )
    if account.height == 0:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No account {request.victim_account!r} in this dataset. "
                "Account identifiers look like AC000123."
            ),
        )

    # The window is fixed by the seeded dataset; an incident outside it has no
    # transactions to trace and would return an empty plan that looks like a
    # failure of the solver rather than of the question.
    window_end = datetime.fromisoformat(settings.sim_end_date)
    window_start = window_end - timedelta(days=settings.sim_days)
    naive = request.incident_time.replace(tzinfo=None)
    if not (window_start <= naive <= window_end + timedelta(days=1)):
        raise HTTPException(
            status_code=422,
            detail=(
                f"The dataset covers {window_start:%Y-%m-%d} to "
                f"{window_end:%Y-%m-%d}. An incident outside that window has "
                "no transactions to trace."
            ),
        )

    row = account.row(0, named=True)

    # A stable id from the inputs, so asking the same question twice reuses the
    # cached context instead of rebuilding it -- and gets the same plan.
    incident_id = (
        f"INTAKE-{request.victim_account}-{naive:%Y%m%d%H%M}"
        f"-{int(request.amount_inr)}-{request.complaint_delay_minutes}"
    )

    incident = Incident(
        incident_id=incident_id,
        episode_id=incident_id,
        ring_id="",
        typology="reported",
        victim_account=request.victim_account,
        amount_inr=request.amount_inr,
        incident_time=naive,
        complaint_delay_minutes=request.complaint_delay_minutes,
        scenario_id="",
    )

    try:
        context = session.context_for(incident)
    except DatasetMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Addressable from here on, so the console can plan, replay and issue
    # orders against it exactly as it does for a seeded scenario.
    session.register_incident(incident)

    return IntakeResponse(
        incident_id=incident_id,
        case_id=references.case_id(incident_id, incident.complaint_time),
        complaint_ref=references.complaint_ref(incident_id, incident.complaint_time),
        victim_account=request.victim_account,
        victim_bank=str(row["bank_id"]),
        victim_district=str(row["district"]),
        amount_inr=request.amount_inr,
        incident_time=naive,
        complaint_time=incident.complaint_time,
        complaint_delay_minutes=request.complaint_delay_minutes,
        channel=request.channel,
        accounts_traced=len(context.state.held),
        candidates_considered=len(context.candidates),
        tainted_still_inside_inr=round(context.state.still_inside, 2),
        tainted_already_gone_inr=round(context.state.exited, 2),
    )
