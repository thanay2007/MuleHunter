"""What a result is worth, in rupees and in people.

One definition of every metric, used by the reports, by the Arena export, and by
the significance tests. The Arena recomputes the same arithmetic in JavaScript so
the numbers move live under the lambda slider; `tools/export_case.py` cross-checks
the two agree before it writes a case file, because two implementations that
silently disagree is exactly the bug a demo cannot survive.

The one definition worth arguing about is `wrongly_frozen`. A freeze does not
lock only the stolen money sitting in an account -- it locks the account. So the
cost of freezing an innocent customer is their own balance *plus* whatever
stolen money happened to be passing through at that moment. Costing it as the
stolen portion alone would price the harm at nearly zero for exactly the
accounts where the harm is real: an ordinary person whose salary is now
unreachable because ₹4,000 of somebody else's money went through last Tuesday.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field


@dataclass
class Balances:
    """Where the stolen money is at any moment, and whose money sits with it."""

    victim: str
    amount_inr: float
    own: dict[str, float]
    #: (t, account, delta) in time order. Deltas are stolen rupees only.
    events: list[tuple[int, str, float]] = field(default_factory=list)

    @classmethod
    def from_case(cls, case: dict) -> "Balances":
        events: list[tuple[int, str, float]] = []
        for transfer in case["transfers"]:
            t = int(transfer["t_offset_sec"])
            events.append((t, transfer["to"], float(transfer["amount_inr"])))
            events.append((t, transfer["from"], -float(transfer["amount_inr"])))
        for cashout in case.get("cashout_events", []):
            events.append(
                (
                    int(cashout["t_offset_sec"]),
                    cashout["account_id"],
                    -float(cashout["amount_inr"]),
                )
            )
        events.sort(key=lambda e: e[0])
        return cls(
            victim=case["victim"]["account_id"],
            amount_inr=float(case["victim"]["amount_inr"]),
            own={a["id"]: float(a.get("balance_before_inr", 0.0)) for a in case["accounts"]}
            if isinstance(case.get("accounts"), list)
            else {},
            events=events,
        )

    def stolen_at(self, account: str, t: int) -> float:
        """Stolen rupees sitting in `account` at time `t`."""
        held = self.amount_inr if account == self.victim else 0.0
        for when, who, delta in self.events:
            if when > t:
                break
            if who == account:
                held += delta
        return max(0.0, held)

    def frozen_at(self, account: str, t: int) -> float:
        """Everything a freeze on `account` at `t` would lock."""
        return self.own.get(account, 0.0) + self.stolen_at(account, t)


def unrecoverable_at(case: dict, t: int) -> float:
    """Stolen rupees that have left the banking system by `t`.

    Read from the cash-out events rather than from the balance deltas: a
    negative delta on a transfer is money moving to another account we can still
    reach, and only a cash-out is gone.
    """
    return round(
        sum(
            float(c["amount_inr"])
            for c in case.get("cashout_events", [])
            if int(c["t_offset_sec"]) <= t
        ),
        2,
    )


def unrecoverable_series(case: dict) -> list[tuple[int, float]]:
    """Cumulative money out of reach, as a step function of time."""
    running = 0.0
    out: list[tuple[int, float]] = [(0, 0.0)]
    for cashout in sorted(case.get("cashout_events", []), key=lambda c: c["t_offset_sec"]):
        running += float(cashout["amount_inr"])
        out.append((int(cashout["t_offset_sec"]), round(running, 2)))
    return out


@dataclass
class Outcome:
    model_id: str
    recovered: float = 0.0
    lost: float = 0.0
    wrongly_frozen: float = 0.0
    customers_impacted: int = 0
    net_benefit: float = 0.0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    median_detection_latency_sec: int | None = None
    first_flag_hop: int | None = None
    status: str = "ok"

    def to_json(self) -> dict:
        return dict(self.__dict__)


def score_case(
    case: dict,
    model_id: str,
    decisions: list[dict],
    truth: dict[str, str],
    layers: dict[str, int],
    lam: float = 1.0,
    status: str = "ok",
) -> Outcome:
    """Every headline number for one system on one case.

    `decisions` is one entry per account the system scored, each carrying
    `decision`, `t_decision_sec` and `score`. Nothing here looks at which system
    produced them.
    """
    balances = Balances.from_case(case)
    out = Outcome(model_id=model_id, status=status)
    if status != "ok":
        out.lost = float(case["victim"]["amount_inr"])
        return out

    latencies: list[int] = []
    for decision in decisions:
        account = decision["account_id"]
        is_mule = truth.get(account) == "mule"
        flagged = decision["decision"] == "flag"
        t = int(decision["t_decision_sec"])

        if flagged and is_mule:
            out.tp += 1
            out.recovered += balances.stolen_at(account, t)
            latencies.append(t)
            hop = layers.get(account)
            if hop is not None:
                out.first_flag_hop = hop if out.first_flag_hop is None else min(out.first_flag_hop, hop)
        elif flagged:
            out.fp += 1
            out.wrongly_frozen += balances.frozen_at(account, t)
        elif is_mule:
            out.fn += 1
        else:
            out.tn += 1

    out.customers_impacted = out.fp
    out.recovered = round(out.recovered, 2)
    out.wrongly_frozen = round(out.wrongly_frozen, 2)
    out.lost = round(float(case["victim"]["amount_inr"]) - out.recovered, 2)
    out.net_benefit = round(out.recovered - lam * out.wrongly_frozen, 2)
    out.median_detection_latency_sec = (
        int(statistics.median(latencies)) if latencies else None
    )
    return out


def no_system_outcome(case: dict) -> Outcome:
    """The anchor every money comparison is read against.

    Without it "we recovered ₹2.6L" is a number with nothing behind it. With it,
    it is ₹2.6L against ₹0, and the reader can see the whole quantity at risk.
    """
    return Outcome(
        model_id="no_system",
        recovered=0.0,
        lost=round(float(case["victim"]["amount_inr"]), 2),
        wrongly_frozen=0.0,
        customers_impacted=0,
        net_benefit=0.0,
    )


def net_benefit_curve(
    case: dict,
    model_id: str,
    decisions: list[dict],
    truth: dict[str, str],
    layers: dict[str, int],
    lambdas: list[float],
) -> list[tuple[float, float]]:
    """Net benefit swept over lambda, for the cost curve report.

    Recovered and wrongly-frozen do not depend on lambda, so this scores once and
    then sweeps -- which is what makes the Arena's slider instant.
    """
    base = score_case(case, model_id, decisions, truth, layers, lam=0.0)
    return [
        (lam, round(base.recovered - lam * base.wrongly_frozen, 2)) for lam in lambdas
    ]


def paired_bootstrap(
    a: list[float], b: list[float], iterations: int = 5000, seed: int = 20260814
) -> dict:
    """Paired bootstrap CI on the per-case difference between two systems.

    Paired because the two systems saw the same cases: the variance that matters
    is in the difference, not in either column. Reports the interval and whether
    it excludes zero, so a two-point win on twelve cases can be called what it
    usually is.
    """
    import random

    if len(a) != len(b) or not a:
        return {"n": 0, "mean_diff": 0.0, "ci_low": 0.0, "ci_high": 0.0, "significant": False}

    diffs = [x - y for x, y in zip(a, b)]
    rng = random.Random(seed)
    n = len(diffs)
    means: list[float] = []
    for _ in range(iterations):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    low = means[int(0.025 * iterations)]
    high = means[int(0.975 * iterations) - 1]
    return {
        "n": n,
        "mean_diff": round(sum(diffs) / n, 2),
        "ci_low": round(low, 2),
        "ci_high": round(high, 2),
        "significant": bool(low > 0 or high < 0),
    }


def mcnemar(a_correct: list[bool], b_correct: list[bool]) -> dict:
    """McNemar on paired flag/no-flag decisions.

    Counts only the decisions where the two systems disagreed, which is the only
    place the comparison carries information. Exact binomial, because the
    discordant counts here are small and the chi-square approximation is not
    trustworthy at this size.
    """
    from math import comb

    b = sum(1 for x, y in zip(a_correct, b_correct) if x and not y)
    c = sum(1 for x, y in zip(a_correct, b_correct) if y and not x)
    n = b + c
    if n == 0:
        return {"b": 0, "c": 0, "p_value": 1.0, "significant": False}
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(k + 1)) / (2**n)
    p = min(1.0, 2 * tail)
    return {"b": b, "c": c, "p_value": round(p, 5), "significant": bool(p < 0.05)}


def spread(values: list[float]) -> dict:
    """Median with min and max, for the seed-spread bars.

    A point estimate is the thing an ML reader distrusts first, and rightly:
    five seeds and a range bar cost nothing and answer the question before it is
    asked.
    """
    if not values:
        return {"median": 0.0, "min": 0.0, "max": 0.0, "n": 0}
    return {
        "median": round(statistics.median(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "n": len(values),
    }
