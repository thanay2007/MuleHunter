"""Deterministic institutional references.

A Cyber Fraud Mitigation Centre desk does not work on "S1". It works on a case
number, against a complaint acknowledgement, and issues numbered instructions.
This module manufactures those identifiers so the console, the freeze order and
the audit trail all quote the *same* strings for the same case.

Two rules hold everything together:

* **hashlib, never `hash()`.** Python salts string hashing per process, so
  `hash("S1")` differs between runs. A case number that changes when the server
  restarts would be the most visible possible violation of the determinism
  guarantee, in the one field a reader instinctively re-reads.
* **Format lives in `config.py`.** Nothing here invents a width or a prefix.

Nothing in this module implies affiliation. The authorities named are formats
borrowed to make the prototype legible to people who work in this domain; every
surface that shows one of these references also carries the non-affiliation
notice.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.config import settings


def _digest(*parts: str) -> int:
    """A stable integer for these parts. Same inputs, same number, forever."""
    payload = "|".join((str(settings.master_seed), *parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _sequence(digits: int, *parts: str) -> str:
    """A zero-padded pseudo-sequence number of the requested width."""
    return str(_digest(*parts) % (10**digits)).zfill(digits)


def case_id(scenario_id: str, complaint_time: datetime) -> str:
    """`CFMC/2026/08/S1-0417` -- authority, period, case within the period."""
    sequence = _sequence(settings.case_ref_digits, "case", scenario_id)
    return (
        f"{settings.case_ref_authority}/{complaint_time:%Y/%m}/"
        f"{scenario_id}-{sequence}"
    )


def complaint_ref(scenario_id: str, complaint_time: datetime) -> str:
    """`NCRP/2026/08/3921046` -- the citizen's complaint acknowledgement."""
    sequence = _sequence(settings.complaint_ref_digits, "complaint", scenario_id)
    return f"{settings.complaint_ref_authority}/{complaint_time:%Y/%m}/{sequence}"


def order_id(scenario_id: str, bank_id: str | None = None) -> str:
    """`FRZ/S1-04821` for the full order, `FRZ/S1-04821/BANK-03` per bank.

    Derived only from the case and the bank, so re-issuing the same order twice
    produces the same number -- a freeze instruction that renumbered itself on
    every download would be worthless as an audit reference.
    """
    sequence = _sequence(settings.order_ref_digits, "order", scenario_id)
    base = f"{settings.order_ref_authority}/{scenario_id}-{sequence}"
    return base if bank_id is None else f"{base}/{bank_id}"


def mask_account(account_id: str) -> str:
    """`AC0173920021` -> `AC01****21`.

    An order for one bank travels to that bank alone, but the whole plan is
    visible on screen and in the audit bundle. Masking is the default because
    the identifiers of accounts belonging to somebody else's customers have no
    business being fully legible outside the bank that holds them.
    """
    keep_start = settings.account_mask_prefix
    keep_end = settings.account_mask_suffix
    if len(account_id) <= keep_start + keep_end:
        return account_id
    hidden = len(account_id) - keep_start - keep_end
    return f"{account_id[:keep_start]}{'*' * hidden}{account_id[-keep_end:]}"


def needs_second_approval(p_mule: float, innocence_cost: float) -> bool:
    """Whether this instruction should not go out on one officer's authority.

    Either the detector is not confident enough, or the modelled harm of being
    wrong about this particular account is high enough to be worth a second
    pair of eyes. Stating which of its own recommendations are shaky is a
    stronger answer to "what if the model is wrong" than any slider.
    """
    return (
        p_mule < settings.second_approval_p_mule
        or innocence_cost > settings.second_approval_innocence_cost
    )
