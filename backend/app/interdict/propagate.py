"""Monte Carlo forward rollout: where is this money about to go?

At the complaint time the money is somewhere, and none of what happens next has
happened yet. The solver cannot plan against transfers it can see, because the
transfers that matter are still in the future. So we forecast them.

**How the forecast is built.** A ring is a business that runs the same route
repeatedly. Every account in it has history: who it forwards to, how fast, in
how many pieces, and whether it cashes out. All of that is observable *before*
this incident, from the ring's previous runs and from ordinary traffic. The
behaviour model fits those distributions per account and samples from them.

Nothing here reads the future or the `is_fraud` label. The forecast is
sometimes wrong, which is exactly why the plan is evaluated against the real
timeline afterwards rather than against its own rollouts.

**The particle representation is the important design choice.** Each rollout
splits the stolen amount into particles, and each particle records the path it
took: the accounts it passed through and the minute it left each one. Recovery
under a freeze set then reduces to *which particles were intercepted*, which
makes the objective a weighted coverage function -- monotone and submodular,
and therefore greedy-approximable with a real guarantee. Chasing flow through a
time-expanded graph for every candidate freeze would be exact and far too slow;
this is exact on the sampled distribution and fast enough to be interactive.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import polars as pl

from app.config import settings
from app.graphstore.build import Dataset, load_dataset
from app.graphstore.trace import TaintState, TransactionIndex, to_epoch, transaction_index

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# behaviour model
# ---------------------------------------------------------------------------


@dataclass
class AccountBehaviour:
    """What one account has historically done with money that arrives."""

    #: Probability it forwards at all rather than holding.
    forward_prob: float
    #: Median minutes between a credit and the onward transfer.
    delay_minutes: float
    #: Spread of that delay, so rollouts are not all identical.
    delay_spread: float
    #: How many pieces it splits into.
    split_count: int
    #: Share of outgoing value that leaves the banking system entirely.
    exit_share: float
    #: Historical recipients, and how often each was used.
    recipients: tuple[str, ...] = ()
    weights: tuple[float, ...] = ()
    exit_nodes: tuple[str, ...] = ()


DEFAULT_BEHAVIOUR = AccountBehaviour(
    forward_prob=0.15,
    delay_minutes=240.0,
    delay_spread=180.0,
    split_count=1,
    exit_share=0.0,
)


@dataclass
class BehaviourModel:
    """Per-account forward-transfer behaviour, fitted from observed history."""

    accounts: dict[str, AccountBehaviour] = field(default_factory=dict)

    def get(self, account: str) -> AccountBehaviour:
        return self.accounts.get(account, DEFAULT_BEHAVIOUR)

    def save(self, path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            account: {
                "forward_prob": behaviour.forward_prob,
                "delay_minutes": behaviour.delay_minutes,
                "delay_spread": behaviour.delay_spread,
                "split_count": behaviour.split_count,
                "exit_share": behaviour.exit_share,
                "recipients": list(behaviour.recipients),
                "weights": list(behaviour.weights),
                "exit_nodes": list(behaviour.exit_nodes),
            }
            for account, behaviour in self.accounts.items()
        }
        path.write_text(json.dumps(payload), encoding="utf-8")


def fit_behaviour(
    accounts: list[str],
    until: datetime,
    dataset: Dataset | None = None,
    index: TransactionIndex | None = None,
) -> BehaviourModel:
    """Fit forwarding behaviour for `accounts` from history before `until`.

    Everything here is a summary of transfers that already happened. An account
    with no history gets `DEFAULT_BEHAVIOUR`: assume it mostly sits on the
    money, which is the right prior for an ordinary account and deliberately
    pessimistic about our ability to predict a fresh mule.
    """
    ds = dataset if dataset is not None else load_dataset()
    idx = index if index is not None else transaction_index()
    keep = set(accounts)

    history = (
        ds.transactions.lazy()
        .filter(pl.col("timestamp") <= until)
        .filter(pl.col("src").is_in(keep))
        .select("src", "dst", "amount", "timestamp")
        .with_columns(pl.col("timestamp").dt.epoch(time_unit="s").alias("epoch"))
        .collect()
    )

    model = BehaviourModel()
    if history.height == 0:
        return model

    # Credits, so we can measure how quickly each debit followed one.
    credits = (
        ds.transactions.lazy()
        .filter(pl.col("timestamp") <= until)
        .filter(pl.col("dst").is_in(keep))
        .select(
            pl.col("dst").alias("src"),
            pl.col("timestamp").dt.epoch(time_unit="s").alias("credit_epoch"),
        )
        .sort("credit_epoch")
        .collect()
    )

    delays = (
        history.sort("epoch")
        # Both sides are sorted by their join key, so each `src` group is too.
        # Polars cannot check that once `by` groups are involved and warns every
        # call; the hint states what the sorts above already guarantee.
        .join_asof(
            credits,
            left_on="epoch",
            right_on="credit_epoch",
            by="src",
            strategy="backward",
            check_sortedness=False,
        )
        .drop_nulls("credit_epoch")
        .with_columns(
            ((pl.col("epoch") - pl.col("credit_epoch")) / 60.0).alias("delay")
        )
        .group_by("src")
        .agg(
            pl.col("delay").median().alias("median_delay"),
            pl.col("delay").quantile(0.25).alias("q25"),
            pl.col("delay").quantile(0.75).alias("q75"),
        )
    )
    delay_by_account = {row["src"]: row for row in delays.iter_rows(named=True)}

    # Splits per credit: how many outgoing transfers an account makes for each
    # one it receives. This is the fan-out the rollout will reproduce.
    inbound_counts = dict(
        ds.transactions.lazy()
        .filter(pl.col("timestamp") <= until)
        .filter(pl.col("dst").is_in(keep))
        .group_by("dst")
        .agg(pl.len().alias("n"))
        .collect()
        .iter_rows()
    )

    grouped = history.group_by("src").agg(
        pl.col("dst"),
        pl.col("amount"),
        pl.len().alias("out_count"),
        pl.col("amount").sum().alias("out_value"),
    )

    for row in grouped.iter_rows(named=True):
        account = row["src"]
        recipients = row["dst"]
        amounts = row["amount"]

        weight_by_target: dict[str, float] = defaultdict(float)
        exit_value = 0.0
        for target, amount in zip(recipients, amounts):
            weight_by_target[target] += float(amount)
            if target in idx.exits:
                exit_value += float(amount)

        exits = tuple(t for t in weight_by_target if t in idx.exits)
        internal = {t: w for t, w in weight_by_target.items() if t not in idx.exits}

        inbound = max(inbound_counts.get(account, 1), 1)
        splits = int(np.clip(round(row["out_count"] / inbound), 1, 16))

        delay_row = delay_by_account.get(account)
        median_delay = float(delay_row["median_delay"]) if delay_row else 60.0
        spread = (
            float((delay_row["q75"] or 0.0) - (delay_row["q25"] or 0.0)) / 2.0
            if delay_row
            else 30.0
        )

        out_value = float(row["out_value"])
        model.accounts[account] = AccountBehaviour(
            # An account that has historically forwarded most of what it
            # received will do so again. Capped below 1 because certainty here
            # is never justified.
            forward_prob=float(np.clip(row["out_count"] / inbound, 0.05, 0.97)),
            delay_minutes=float(np.clip(median_delay, 0.5, 720.0)),
            delay_spread=float(np.clip(abs(spread), 0.5, 360.0)),
            split_count=splits,
            exit_share=float(exit_value / out_value) if out_value > 0 else 0.0,
            recipients=tuple(sorted(internal)),
            weights=tuple(internal[t] for t in sorted(internal)),
            exit_nodes=exits,
        )

    return model


# ---------------------------------------------------------------------------
# rollouts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Particle:
    """One indivisible parcel of the stolen money, and the route it took.

    `hops` pairs each account the parcel passed through with the minute it
    *left* that account. A freeze on account `a` issued at or before that
    minute intercepts this parcel -- that comparison is the entire objective.
    """

    rollout: int
    value: float
    hops: tuple[tuple[str, int], ...]
    exited: bool
    exit_minute: int

    @property
    def accounts(self) -> tuple[str, ...]:
        return tuple(account for account, _ in self.hops)


@dataclass
class RolloutSet:
    """Cached Monte Carlo rollouts for one incident.

    Cached because the greedy solver evaluates thousands of candidate freezes
    against these same particles. Regenerating them per evaluation is the
    difference between a two-second answer and a three-minute one.
    """

    incident_id: str
    n_rollouts: int
    particles: tuple[Particle, ...]
    amount_inr: float
    complaint_minute: int

    #: Particle values as an array, for vectorised marginal-gain arithmetic.
    values: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.values = np.array(
            [p.value for p in self.particles], dtype=np.float64
        )

    @property
    def expected_leak(self) -> float:
        """Rupees expected to leave the banking system with no intervention."""
        leaked = sum(p.value for p in self.particles if p.exited)
        return leaked / self.n_rollouts

    def blocking_index(self) -> dict[str, dict[int, int]]:
        """account -> {particle index: minute the money left that account}.

        The core lookup for the solver: freezing `account` at minute `t`
        intercepts exactly the particles whose recorded departure minute is at
        or after `t`.
        """
        index: dict[str, dict[int, int]] = defaultdict(dict)
        for i, particle in enumerate(self.particles):
            for account, minute in particle.hops:
                current = index[account].get(i)
                if current is None or minute < current:
                    index[account][i] = minute
        return index


def run_rollouts(
    state: TaintState,
    behaviour: BehaviourModel,
    incident_id: str,
    n_rollouts: int | None = None,
    seed: int | None = None,
    index: TransactionIndex | None = None,
) -> RolloutSet:
    """Simulate the money forward from the complaint time, `n` times."""
    idx = index if index is not None else transaction_index()
    rollouts = n_rollouts or settings.n_rollouts
    rng = np.random.default_rng(
        seed if seed is not None else settings.master_seed
    )

    per_rollout = settings.particles_per_rollout
    horizon_minutes = settings.incident_horizon_hours * 60
    complaint_minute = state.minute_of(state.until)

    # Only money still inside the banking system can be saved. Whatever already
    # left is gone and is not represented -- counting it would inflate every
    # recovery figure by exactly the amount nobody can do anything about.
    holdings = {a: v for a, v in state.held.items() if v > settings.taint_floor_inr}
    total_held = sum(holdings.values())

    particles: list[Particle] = []
    if total_held <= 0:
        return RolloutSet(
            incident_id=incident_id,
            n_rollouts=rollouts,
            particles=(),
            amount_inr=state.amount_inr,
            complaint_minute=complaint_minute,
        )

    accounts = list(holdings)
    shares = np.array([holdings[a] for a in accounts]) / total_held
    parcel_value = total_held / per_rollout

    for rollout in range(rollouts):
        counts = rng.multinomial(per_rollout, shares)
        for account, count in zip(accounts, counts):
            for _ in range(int(count)):
                particles.append(
                    _walk(
                        rng,
                        behaviour,
                        idx,
                        start=account,
                        start_minute=complaint_minute,
                        value=parcel_value,
                        rollout=rollout,
                        horizon=horizon_minutes,
                    )
                )

    return RolloutSet(
        incident_id=incident_id,
        n_rollouts=rollouts,
        particles=tuple(particles),
        amount_inr=state.amount_inr,
        complaint_minute=complaint_minute,
    )


def _walk(
    rng: np.random.Generator,
    behaviour: BehaviourModel,
    index: TransactionIndex,
    start: str,
    start_minute: int,
    value: float,
    rollout: int,
    horizon: int,
) -> Particle:
    """Walk one parcel forward until it exits, settles, or runs out of horizon.

    Every account the parcel *rests in* is recorded, including the one it
    finally settles in, paired with the minute it leaves. A parcel that never
    moves again is recorded with a departure past the horizon, so a freeze on
    that account still captures it. Recording only the accounts money moves
    *through* would value a freeze on a parked ₹4,00,000 at exactly zero.
    """
    hops: list[tuple[str, int]] = []
    account = start
    minute = start_minute
    seen: set[str] = set()
    settled = horizon + 1

    for _ in range(settings.max_rollout_hops):
        profile = behaviour.get(account)
        if rng.random() > profile.forward_prob:
            hops.append((account, settled))  # the money settles here
            break

        # Delay drawn around the account's observed median, so the spread of
        # arrival times across rollouts matches the spread actually observed.
        delay = abs(
            rng.normal(profile.delay_minutes, max(profile.delay_spread, 0.5))
        )
        minute = minute + int(max(1, round(delay)))
        hops.append((account, minute))

        if minute > horizon:
            return Particle(
                rollout=rollout,
                value=value,
                hops=tuple(hops),
                exited=False,
                exit_minute=minute,
            )

        # Does it leave the banking system here?
        if profile.exit_nodes and rng.random() < profile.exit_share:
            return Particle(
                rollout=rollout,
                value=value,
                hops=tuple(hops),
                exited=True,
                exit_minute=minute,
            )

        if not profile.recipients:
            hops.append((account, settled))
            break

        weights = np.asarray(profile.weights, dtype=np.float64)
        total = weights.sum()
        if total <= 0:
            hops.append((account, settled))
            break
        nxt = str(rng.choice(profile.recipients, p=weights / total))

        if nxt in index.exits:
            return Particle(
                rollout=rollout,
                value=value,
                hops=tuple(hops),
                exited=True,
                exit_minute=minute,
            )
        if nxt in seen:
            hops.append((nxt, settled))  # do not loop forever around a cycle
            break
        seen.add(nxt)
        account = nxt

    return Particle(
        rollout=rollout,
        value=value,
        hops=tuple(hops),
        exited=False,
        exit_minute=minute,
    )
