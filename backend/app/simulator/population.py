"""Legitimate account population and background transaction traffic.

Everything here is vectorised with numpy. Generating a quarter of a million
transactions in a Python loop is possible but slow enough to make iteration
painful, and the acceptance budget is 60 seconds for the whole dataset.

Determinism: every random draw comes from a `numpy.random.Generator` passed in
by the caller. No module-level RNG, no `random` module, no wall-clock reads.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import polars as pl

from app.config import settings
from app.simulator.scenarios import SCENARIOS

# Eight fictional banks. Three-letter codes are the only all-caps text in the
# product. These deliberately do not correspond to any real institution.
BANKS: tuple[str, ...] = ("ANB", "BKC", "CVB", "DSB", "ENB", "FMB", "GTB", "HRB")

# Market share is uneven, as it is in reality -- a few large banks and a tail.
BANK_WEIGHTS: tuple[float, ...] = (0.22, 0.18, 0.15, 0.12, 0.11, 0.09, 0.08, 0.05)

# Real Indian district names. District is geography, not personal data.
DISTRICTS: tuple[str, ...] = (
    "Mumbai Suburban", "Pune", "Thane", "Nagpur", "Nashik", "Ahmedabad",
    "Surat", "Vadodara", "Rajkot", "New Delhi", "North Delhi", "Gurugram",
    "Faridabad", "Bengaluru Urban", "Mysuru", "Belagavi", "Chennai",
    "Coimbatore", "Madurai", "Hyderabad", "Rangareddy", "Warangal",
    "Visakhapatnam", "Guntur", "Kolkata", "Howrah", "North 24 Parganas",
    "Patna", "Gaya", "Muzaffarpur", "Lucknow", "Kanpur Nagar", "Varanasi",
    "Ghaziabad", "Agra", "Jaipur", "Jodhpur", "Kota", "Indore", "Bhopal",
    "Jabalpur", "Ludhiana", "Amritsar", "Ernakulam", "Thiruvananthapuram",
    "Bhubaneswar", "Ranchi", "Raipur", "Dehradun", "Guwahati",
)


def _district_weights() -> np.ndarray:
    """Zipf-ish weighting so metros dominate, as they do in real UPI volume."""
    ranks = np.arange(1, len(DISTRICTS) + 1, dtype=np.float64)
    weights = 1.0 / ranks**0.65
    return weights / weights.sum()


def _exact_counts(shares: dict[str, float], total: int) -> dict[str, int]:
    """Split `total` by `shares` using largest remainder, so counts sum exactly."""
    raw = {k: v * total for k, v in shares.items()}
    counts = {k: int(np.floor(v)) for k, v in raw.items()}
    shortfall = total - sum(counts.values())
    if shortfall:
        order = sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)
        for k in order[:shortfall]:
            counts[k] += 1
    return counts


#: Fixed reference for epoch conversion. `datetime.timestamp()` is deliberately
#: never used anywhere in the simulator: it interprets naive datetimes in the
#: machine's local timezone, which would make the dataset depend on where it was
#: generated and break byte-identical reproduction.
EPOCH_REF = datetime(1970, 1, 1)


def to_epoch(when: datetime) -> int:
    return int((when - EPOCH_REF).total_seconds())


def account_id(index: int) -> str:
    return f"AC{index:06d}"


def window_bounds() -> tuple[date, date]:
    end = date.fromisoformat(settings.sim_end_date)
    start = end - timedelta(days=settings.sim_days - 1)
    return start, end


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------


def build_accounts(rng: np.random.Generator) -> pl.DataFrame:
    """Generate the retail account population.

    Archetype counts are exact rather than sampled, so the hard-negative class
    is always present in the intended proportion. The first
    `len(SCENARIOS)` rows are reserved for scenario victims and are stamped
    with the district and archetype their story requires.
    """
    n = settings.n_accounts
    _, end = window_bounds()

    shares = settings.archetype_shares
    total_share = sum(shares.values())
    if abs(total_share - 1.0) > 1e-9:
        raise ValueError(f"archetype_shares must sum to 1.0, got {total_share}")

    counts = _exact_counts(shares, n)
    archetypes = np.repeat(
        np.array(list(counts.keys()), dtype=object),
        np.array(list(counts.values())),
    )
    rng.shuffle(archetypes)

    banks = rng.choice(len(BANKS), size=n, p=np.array(BANK_WEIGHTS))
    districts = rng.choice(len(DISTRICTS), size=n, p=_district_weights())

    # Account age: heavy tail, most accounts a few years old.
    age_days = rng.integers(30, 8 * 365, size=n)
    open_dates = np.array([end - timedelta(days=int(d)) for d in age_days])

    # KYC tier correlates with archetype in reality; video-KYC accounts skew
    # young and are over-represented among rented accounts.
    kyc = rng.choice(
        np.array(["full", "small", "video"], dtype=object),
        size=n,
        p=np.array([0.72, 0.16, 0.12]),
    )

    # Device fingerprints drawn from a pool smaller than the population, so
    # natural sharing occurs among legitimate users too.
    pool = max(1, int(n * settings.legit_device_pool_ratio))
    device_idx = rng.integers(0, pool, size=n)

    # IP prefix is tied to district, so geography and network correlate.
    ip_sub = rng.integers(0, 24, size=n)

    accounts = pl.DataFrame(
        {
            "account_id": [account_id(i) for i in range(n)],
            "bank_id": [BANKS[i] for i in banks],
            "open_date": open_dates,
            "kyc_tier": kyc.tolist(),
            "archetype": archetypes.tolist(),
            "district": [DISTRICTS[i] for i in districts],
            "device_fingerprint": [f"DV{i:06d}" for i in device_idx],
            "home_ip_prefix": [
                f"10.{d}.{s}.0/24" for d, s in zip(districts.tolist(), ip_sub.tolist())
            ],
        }
    )

    return _stamp_scenario_victims(accounts)


def _stamp_scenario_victims(accounts: pl.DataFrame) -> pl.DataFrame:
    """Give the reserved head rows the district/archetype each story needs."""
    district = accounts["district"].to_list()
    archetype = accounts["archetype"].to_list()

    for slot, scenario in enumerate(SCENARIOS):
        district[slot] = scenario.victim_district
        archetype[slot] = scenario.victim_archetype

    return accounts.with_columns(
        pl.Series("district", district),
        pl.Series("archetype", archetype),
    )


def build_exit_nodes() -> pl.DataFrame:
    """Cash-out infrastructure: where money leaves the banking system.

    These are graph nodes rather than retail accounts and sit outside
    `n_accounts`. Exchange deposit accounts are deliberately few and shared
    across rings, which is what makes them high-value interdiction targets.
    """
    rows: list[dict[str, object]] = []

    def add(node_id: str, kind: str, district: str) -> None:
        rows.append(
            {
                "account_id": node_id,
                "bank_id": "EXT",
                "open_date": date.fromisoformat(settings.sim_end_date),
                "kyc_tier": "none",
                "archetype": "exit_point",
                "district": district,
                "device_fingerprint": f"DEV-{kind}",
                "home_ip_prefix": "0.0.0.0/0",
                "exit_kind": kind,
            }
        )

    for i in range(settings.n_atm_exits):
        add(f"EXIT-ATM-{i:03d}", "atm", DISTRICTS[i % len(DISTRICTS)])
    for i in range(settings.n_exchange_exits):
        add(f"EXIT-XCH-{i:03d}", "exchange", "Mumbai Suburban")
    for i in range(settings.n_crossborder_exits):
        add(f"EXIT-XBR-{i:03d}", "crossborder", "New Delhi")

    return pl.DataFrame(rows)


# ---------------------------------------------------------------------------
# background traffic
# ---------------------------------------------------------------------------


def _regular_counterparties(
    rng: np.random.Generator, districts: np.ndarray, n: int
) -> np.ndarray:
    """Each account's small set of repeat counterparties.

    Repeat structure is what gives the graph genuine communities for Louvain
    to find, and makes recipient-set overlap a meaningful feature rather than
    noise.
    """
    k = settings.n_regular_counterparties
    regulars = rng.integers(0, n, size=(n, k))

    # Bias a share of them toward the same district.
    local_mask = rng.random((n, k)) < settings.same_district_prob
    for d in np.unique(districts):
        members = np.flatnonzero(districts == d)
        if members.size < 2:
            continue
        picks = members[rng.integers(0, members.size, size=(members.size, k))]
        block = regulars[members]
        sub = local_mask[members]
        block[sub] = picks[sub]
        regulars[members] = block

    return regulars


def _day_weights(start: date, days: int) -> np.ndarray:
    """Non-uniform day weights: salary-day and festival spikes."""
    festivals = {date.fromisoformat(d) for d in settings.festival_dates}
    weights = np.ones(days, dtype=np.float64)
    for i in range(days):
        day = start + timedelta(days=i)
        if day.day in settings.salary_days_of_month:
            weights[i] *= settings.salary_day_multiplier
        if day in festivals:
            weights[i] *= settings.festival_day_multiplier
    return weights / weights.sum()


def build_background_transactions(
    rng: np.random.Generator,
    accounts: pl.DataFrame,
    exit_nodes: pl.DataFrame,
    active: np.ndarray,
) -> pl.DataFrame:
    """Ordinary, non-fraudulent traffic across the whole population.

    `active` masks out mule accounts, which were dormant for months before
    activation and so contribute no background traffic by construction.
    """
    n = accounts.height
    start, _ = window_bounds()
    archetypes = accounts["archetype"].to_numpy()
    districts_str = accounts["district"].to_numpy()
    district_codes = np.searchsorted(np.array(DISTRICTS), districts_str)

    # --- how many transactions each account sends -------------------------
    rates = np.array(
        [settings.daily_txn_rate[a] for a in archetypes], dtype=np.float64
    )
    rates = np.where(active, rates, 0.0)
    expected = rates * settings.sim_days

    # One global factor puts the total on target while preserving the relative
    # activity of each archetype. See simulator/README.md.
    scale = settings.target_transactions / max(expected.sum(), 1.0)
    counts = rng.poisson(expected * scale)
    total = int(counts.sum())

    src = np.repeat(np.arange(n), counts)

    # --- counterparties ---------------------------------------------------
    regulars = _regular_counterparties(rng, district_codes, n)
    use_regular = rng.random(total) < settings.regular_counterparty_prob
    slot = rng.integers(0, settings.n_regular_counterparties, size=total)
    dst = np.where(use_regular, regulars[src, slot], rng.integers(0, n, size=total))

    # Never let an account pay itself.
    clash = dst == src
    while clash.any():
        dst[clash] = rng.integers(0, n, size=int(clash.sum()))
        clash = dst == src

    # --- amounts ----------------------------------------------------------
    mu = np.array([settings.amount_lognormal[a][0] for a in archetypes])
    sigma = np.array([settings.amount_lognormal[a][1] for a in archetypes])
    amounts = rng.lognormal(mu[src], sigma[src])
    amounts = np.round(np.clip(amounts, 10.0, 4_000_000.0), 2)

    # --- timing -----------------------------------------------------------
    day_p = _day_weights(start, settings.sim_days)
    days = rng.choice(settings.sim_days, size=total, p=day_p)

    hour_p = np.array(settings.diurnal_weights)
    hour_p = hour_p / hour_p.sum()
    hours = rng.choice(24, size=total, p=hour_p)

    minutes = rng.integers(0, 60, size=total)
    seconds = rng.integers(0, 60, size=total)

    base = to_epoch(datetime(start.year, start.month, start.day))
    epoch = base + days * 86400 + hours * 3600 + minutes * 60 + seconds

    # --- channel ----------------------------------------------------------
    channel_names = np.array(list(settings.channel_weights.keys()), dtype=object)
    channel_p = np.array(list(settings.channel_weights.values()))
    channel_p = channel_p / channel_p.sum()
    channels = rng.choice(len(channel_names), size=total, p=channel_p)

    account_ids = accounts["account_id"].to_numpy()
    devices = accounts["device_fingerprint"].to_numpy()
    ips = accounts["home_ip_prefix"].to_numpy()

    src_ids = account_ids[src]
    dst_ids = account_ids[dst].astype(object)

    # ATM withdrawals terminate at an ATM node in the sender's district.
    atm_code = int(np.flatnonzero(channel_names == "ATM_WITHDRAWAL")[0])
    is_atm = channels == atm_code
    if is_atm.any():
        atm_ids = exit_nodes.filter(pl.col("exit_kind") == "atm")["account_id"].to_numpy()
        picks = district_codes[src[is_atm]] % len(atm_ids)
        dst_ids[is_atm] = atm_ids[picks]
        # An ATM cannot dispense more than the daily cap.
        amounts[is_atm] = np.minimum(amounts[is_atm], settings.atm_withdrawal_cap_inr)

    frame = pl.DataFrame(
        {
            "src": src_ids,
            "dst": dst_ids,
            "amount": amounts,
            "epoch": epoch,
            "channel": [str(channel_names[c]) for c in channels],
            "device_fingerprint": devices[src],
            "ip_prefix": ips[src],
            "is_fraud": np.zeros(total, dtype=bool),
            "ring_id": np.full(total, "", dtype=object),
        }
    )

    return _add_salary_credits(rng, frame, accounts, active)


def _add_salary_credits(
    rng: np.random.Generator,
    frame: pl.DataFrame,
    accounts: pl.DataFrame,
    active: np.ndarray,
) -> pl.DataFrame:
    """Monthly salary from a small employer pool.

    Employers become genuine hubs in the graph, which matters: without them a
    high in-degree node looks inherently suspicious, and plenty of legitimate
    accounts have high in-degree.
    """
    start, _ = window_bounds()
    archetypes = accounts["archetype"].to_numpy()
    account_ids = accounts["account_id"].to_numpy()
    devices = accounts["device_fingerprint"].to_numpy()
    ips = accounts["home_ip_prefix"].to_numpy()

    hnw = np.flatnonzero((archetypes == "hnw") & active)
    if hnw.size == 0:
        return frame
    employers = hnw[: settings.n_employers] if hnw.size >= settings.n_employers else hnw

    earners = np.flatnonzero((archetypes == "salaried") & active)
    if earners.size == 0:
        return frame

    # Which in-window days are pay days?
    pay_days = [
        i
        for i in range(settings.sim_days)
        if (start + timedelta(days=i)).day in settings.salary_days_of_month
    ]
    if not pay_days:
        return frame

    n = earners.size
    employer_of = employers[rng.integers(0, employers.size, size=n)]
    day = np.array(pay_days)[rng.integers(0, len(pay_days), size=n)]
    hour = rng.integers(9, 19, size=n)
    minute = rng.integers(0, 60, size=n)
    second = rng.integers(0, 60, size=n)

    base = to_epoch(datetime(start.year, start.month, start.day))
    epoch = base + day * 86400 + hour * 3600 + minute * 60 + second

    mu, sigma = settings.salary_lognormal
    amounts = np.round(np.clip(rng.lognormal(mu, sigma, size=n), 8_000.0, 900_000.0), 2)

    salaries = pl.DataFrame(
        {
            "src": account_ids[employer_of],
            "dst": account_ids[earners].astype(object),
            "amount": amounts,
            "epoch": epoch,
            "channel": ["NEFT"] * n,
            "device_fingerprint": devices[employer_of],
            "ip_prefix": ips[employer_of],
            "is_fraud": np.zeros(n, dtype=bool),
            "ring_id": np.full(n, "", dtype=object),
        }
    )

    return pl.concat([frame, salaries], how="vertical")