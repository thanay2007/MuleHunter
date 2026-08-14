# The Chakravyuh transaction simulator

**Every number in this dataset is synthetic.** There is no real bank data, no real PII,
and no real account numbers anywhere in this repository. Real inter-bank transaction data
is not obtainable for a hackathon — or for most research — so the generator is treated as
a first-class deliverable and open-sourced with the rest of the code.

This document exists so that a reviewer can audit every distribution choice rather than
take our word for it. Where a value comes from a public figure, it is cited. **Where a
value is an assumption, it is labelled as an assumption.** We would rather state a
limitation than have it found.

---

## Why synthetic data is defensible here

The system being evaluated is an **optimiser**, not a classifier. What it needs from the
data is *structure*: layering depth, timing of cash-out, fan-out shape, and the presence
of hard negatives. Those structural properties are publicly documented in I4C and RBI
reporting even though the underlying transactions are not public.

The risk of synthetic data is that you accidentally generate a problem that is easier
than reality and then report flattering numbers. The three defences used here:

1. **Hard negatives are 8% of the population and actually behave like it.** Legitimate
   high-velocity accounts (chit fund operators, travel agents, wholesale traders) take
   money in and push it straight back out, wide, within minutes — see *pass-through
   traffic* below. They are guaranteed never to be labelled as mules.
2. **The tells are noisy, not exclusive.** Only 55% of ring accounts share a device, 70%
   show a dormancy break, and 60% were opened in a co-ordinated window. Legitimate
   accounts share devices routinely. If every mule carried every tell the classes would
   separate perfectly, both models would score ~1.00 AUC-PR, and the benchmark would
   measure nothing.
3. **Mules keep ordinary traffic.** After activation, a rented account carries on being a
   real person's account at a reduced rate. Without this, "has no background activity"
   separates mules perfectly and the whole detection problem evaporates.
4. **Some laundering hops land on genuinely innocent accounts.** 14% of hops pay a real
   merchant instead of the next mule. Without this every account holding stolen money is
   a mule, freezing has no collateral cost, and the innocence budget is decoration.
5. **Four structurally different typologies.** A detector tuned to fan-out width misses
   chain-and-burst; one tuned to large transfers misses structuring by construction.

Each of these was added *after* observing the failure it prevents. The contrast report
printed by `python -m app.detect.train` is the running check: it asserts that mules and
hard negatives are **not** separable on velocity, and that they **are** separable on
shared infrastructure.

---

## Determinism

One master seed (`config.master_seed`) drives a `numpy.random.SeedSequence` whose children
are spawned in a fixed order — population, rings, background traffic, episodes. The same
seed produces **byte-identical** parquet files, verified by a test that generates the
dataset twice and compares SHA-256 digests.

Two rules make this hold, and both are easy to break by accident:

- **Nothing reads the wall clock.** The simulation window is anchored to a fixed
  `sim_end_date`, not to "today".
- **`datetime.timestamp()` is never used.** It interprets naive datetimes in the machine's
  local timezone, which would make the dataset depend on *where* it was generated. All
  epoch conversion goes through `population.to_epoch()` against a fixed reference.

---

## Population — 40,000 accounts, 8 fictional banks

Bank codes (`ANB`, `BKC`, `CVB`, …) are invented and correspond to no real institution.
Market share is deliberately uneven (22% down to 5%) because a uniform split would make
the cross-bank coordination story artificially easy.

District names **are** real Indian districts. District is geography, not personal data.
They are weighted Zipf-like (exponent 0.65) so metros dominate, matching the concentration
of reported UPI volume.

### Archetype mix

| Archetype | Share | Rationale |
|---|---:|---|
| Salaried | 42% | Monthly credit, steady debits, balance floor |
| Small merchant | 18% | Many small UPI credits daily, periodic sweep-out |
| Student | 12% | Low balance, high count, small amounts, P2P heavy |
| Homemaker / low activity | 15% | Sparse, low velocity |
| High-net-worth | 5% | Large infrequent transfers; also the employer pool |
| **Legitimate high-velocity** | **8%** | **The hard negatives. See above.** |

*Assumption.* These shares are a plausible retail mix, not a measured national
distribution. What matters for the evaluation is that the hard-negative class is large
enough to actually damage a careless model's precision — 3,200 accounts is.

### Amounts

Log-normal per archetype on `log(INR)`. Salaried `μ=7.4, σ=1.05` gives a median around
₹1,600 with a long tail; HNW `μ=10.2, σ=1.20` gives a median near ₹27,000 with tails into
the lakhs. *Assumption*, calibrated to typical retail UPI ticket sizes rather than to a
published distribution.

### Timing

A 24-point diurnal curve peaking near **11:00 and 20:00 IST**, shaped to reported NPCI
intraday UPI volume. Salary days (1st–3rd of month) carry a 3.2× multiplier; two festival
dates carry 2.1×.

### Graph structure

Transfers do not go to uniformly random accounts — that would produce a graph with no
community structure, making Louvain meaningless and recipient-set overlap pure noise.
Instead each account has **8 regular counterparties** (55% biased to its own district) and
sends to one of them 72% of the time.

Salary credits flow from a pool of **220 employer accounts**, which become genuine hubs.
This matters: without them, high in-degree would look inherently suspicious, when in
reality plenty of legitimate accounts have it.

### Pass-through traffic — what makes the hard negatives hard

`legit_high_velocity` accounts do not just transact often; they **forward**. 72% of the
credits they receive are swept back out within 1.5–25 minutes, split 3–9 ways to their
regular counterparties, keeping a 3–18% working margin.

This is the single most important behaviour in the generator, and it was missing from the
first version. With independent in/out timing, every legitimate account had a residence
time measured in *days* while mules forwarded in *minutes* — so "money left within ten
minutes" separated the classes almost perfectly and every detector scored ~0.99. That
number was an artefact of the traffic model, and it would have collapsed the first time
the system met a real chit fund.

With pass-through enabled, the hard negatives are *faster* than the mules:

| Feature | Mule (median) | Legit high-velocity | Other legitimate |
|---|---:|---:|---:|
| Residence before forwarding | 40.5 min | **16.7 min** | 2,363 min |
| Forwarded within 10 min | 0% | **28%** | 0% |
| Turnover ratio | 0.90 | **9.5** | 0.14 |

The consequence is exactly what it should be: the **rules baseline collapses to ~12%
precision**, because it is drowning in innocent chit fund operators.

### Dormancy needs a pre-window history

The generator emits 30 days of traffic, but a real account has years of it. "Days since
last activity" measured inside the window would flag every *old legitimate* account and
nothing else — the feature would be an artefact of the window length.

So the account table carries `prior_activity_date`: when the account last moved money
*before* the window opened. Legitimate accounts get a gap drawn from their own activity
rate (which correctly leaves genuinely sparse archetypes such as homemakers looking
dormant-ish — that is a hard negative, and it should be hard). Mule accounts are
overwritten to have been untouched since opening, which is the tell that actually
distinguishes them. Banks do know this date, so it is fair to use.

---

## Mule rings — 12 rings, 4 typologies, 3 each

Mule accounts are **real accounts belonging to real people**, rented or sold — not
fabricated identities. So they are drawn from the *existing* population, skewed toward the
archetypes syndicates actually recruit from (student 45%, homemaker 35%, salaried 20%),
and then have their opening, device and dormancy attributes rewritten to the ring pattern.
`legit_high_velocity` accounts are never recruited, so they stay clean as hard negatives.

Resulting prevalence is **~1.4% of accounts**, which sits in a realistic band. A dataset
that was 30% mule would make every downstream metric meaningless.

### The four typologies

| Typology | Shape | What it defeats |
|---|---|---|
| **Fan-out layering** | Collector splits 6–14 ways, 4–8 layers deep, 3–15 min per hop | Nothing — this is the classic case |
| **Chain-and-burst** | Narrow chain (fan-out 1–2) for 4 hops, then bursts 8–16 wide | Fan-out threshold rules |
| **Structuring** | Every transfer held in ₹45,000–49,900, many parallel paths | ₹50,000 reporting-threshold rules |
| **Crypto exit** | 2–3 hops, terminates at a few shared exchange deposit accounts | Depth-based heuristics |

Ring size is capped at 60–180 accounts. Unbounded branching would explode past any
realistic ring, so the size budget is allocated across the depth rather than compounded
freely. Reported syndicate rings run from a few dozen to a few hundred accounts.

Depth and per-hop delay are set so a chain takes most of the reported 60–90 minute
window rather than completing in ten. This matters for more than realism: if layering
finishes before anyone can complain, there is nothing left to decide and the interdiction
problem is vacuous. At S1's 42-minute complaint delay the money is genuinely mid-flight,
which is what makes freezing *upstream* worth more than freezing at the exit.

### Shared infrastructure — the signal that beats per-account rules

This is the core modelling claim of the project, so it is worth being explicit about what
is injected:

- **4–10 accounts share one `device_fingerprint`**, in clusters within a ring — but only
  **55%** of ring accounts get one. Careful operators use a separate handset.
- **Clusters share an `ip_prefix`.** The legitimate IP pool is wide enough that an
  ordinary /24 holds 2–3 accounts; too narrow a pool and *ordinary* accounts end up in
  larger IP clusters than rings do, which inverts the feature and teaches the detector
  precisely the wrong thing. (This was a real bug, caught by the contrast report.)
- **Accounts are opened within a 21-day window** — but only **60%** of them. The rest are
  recruited later, months apart.
- **Accounts are dormant 4–14 months before activation** — but only **70%**. Some accounts
  are bought while already in use and show no dormancy break at all.
- **Recipient sets overlap** across accounts that look otherwise unrelated.

None of these is individually conclusive, all of them occur in the legitimate population
at some rate, and **no ring account is guaranteed to carry any of them**. That last point
is deliberate and it is the whole argument: the accounts carrying no individual tell are
individually unremarkable and damning only through their neighbourhood, which is exactly
the case a per-account model structurally cannot reach.

The strongest neighbourhood feature turns out to be `device_peers_in_incident` — how many
accounts on the same handset are standing in the path of *this* stolen money. A shared
device alone is weak; two ordinary accounts sharing a phone will essentially never
co-occur in one incident, while eight accounts from one ring always will.

### Cash-out

Money exits within **45–90 minutes** of the victim credit, consistent with I4C reporting
that funds typically leave the banking system inside that window. Exits are capped at
realistic per-window limits: ₹25,000 per ATM withdrawal, ₹2,00,000 per exchange deposit,
₹5,00,000 cross-border.

Exchange deposit accounts are deliberately **few (6) and shared across rings**, which is
what makes them disproportionately valuable interdiction targets — and is exactly the kind
of structure a per-account classifier cannot exploit.

Any ring node with no onward transfer is a cash-out node, not just the final layer:
fan-out trees terminate at leaves scattered across several depths and every one of them
is an exit.

Cash-out is scheduled as `max(arrival + 2–15 min, episode start + 45–90 min)`. The
calibrated 45–90 minute window is measured from the *victim credit*, but a deep chain can
still be moving at minute 90 — scheduling purely from the episode start had money leaving
accounts before it ever arrived, stranding large sums permanently and silently corrupting
every recovery figure downstream.

### Laundering through innocent accounts

**14% of laundering hops pay a genuinely legitimate account** — a real merchant or
high-velocity trader — instead of the next mule. The money stops there; it was a real
payment and the recipient has no onward role.

Routing through real businesses is deliberate tradecraft (a payment to a real merchant is
excellent cover), but the modelling reason is sharper: without it, *every* account holding
stolen money is a mule, freezing carries no collateral cost, and the innocence budget
prices a risk that does not exist. With it, some of the accounts sitting on the victim's
money belong to a shopkeeper who sold somebody a phone — and the solver has to decide
whether freezing them is worth it.

These accounts are drawn only from `small_merchant` and `legit_high_velocity`, neither of
which is ever recruited as a mule, so they are innocent by construction.

---

## Scenarios

Six fixed incidents, each with a pinned seed, drive the demo and the API. Victim accounts
are reserved slots at the head of the account table (`AC000000`–`AC000005`) so a
scenario's victim is known at import time while still carrying the district and archetype
its story requires.

| id | Scenario | Amount | Complaint delay | Ring |
|---|---|---:|---:|---|
| S1 | Digital arrest — retired teacher, Pune | ₹15,00,000 | 42 min | fan-out |
| S2 | Investment scam — Telegram group, Surat | ₹8,50,000 | 6 h | structuring |
| S3 | UPI collect fraud — student, Patna | ₹62,000 | 11 min | chain-and-burst |
| S4 | Task scam — homemaker, Nagpur | ₹3,20,000 | 2 h | crypto exit |
| S5 | Deepfake CEO transfer — SME, Ahmedabad | ₹47,00,000 | 25 min | fan-out ×2 |
| S6 | Loan app extortion — gig worker, Delhi | ₹1,10,000 | 90 min | structuring |

S5 launders through two structurally separate rings: the collector bridges 35–50% of the
money into a second ring, which is why freezing "the ring" is not a well-defined action
and freezing *a chosen set of accounts* is.

Each ring also runs **14–20 additional randomised episodes**. A syndicate ring is a
business: it runs continuously, not once. The range is set so the four held-out rings
alone supply enough distinct incidents (69 episodes) to fill the 200-incident benchmark
without ever reusing a training ring.

Episodes are written to `data/episodes.parquet` as a first-class artifact rather than
inferred later from transaction shape.

### The train / hold-out split

Rings `RING-01`, `RING-05`, `RING-09` and `RING-12` — one per typology — are kept out of
detector training entirely.

`RING-01` is scenario **S1**, the stage demo. That is deliberate: the demo runs against a
ring the detector has never seen. Any other arrangement makes the live numbers meaningless,
and it is the first thing a good judge will ask about.

---

## Known limitations

Stated plainly, because a judge will ask:

1. **Account balances are not modelled.** Transfers are generated from behavioural rates,
   not from a running balance with an overdraft constraint. This means a mule's
   "transferable amount" in the propagation model is an estimate from observed flow rather
   than a known cash position.
2. **Ring behaviour is stationary across the window.** Real syndicates adapt to enforcement
   within days; these rings run the same route for thirty. There *is* an adaptive
   adversary in the evaluation — blocked money reroutes to another account the operator
   controls, and the benchmark reports every headline both ways — but that models
   adaptation *within* an incident, not a syndicate that changes its topology in response
   to being interdicted last week.
3. **One geography, one currency, no cross-border leg is actually simulated** beyond the
   exit node — cross-border exits are modelled as a capacity-limited sink, not as a real
   correspondent banking chain.
4. **Amount distributions are assumptions**, not fits to measured data. The structural
   properties (layering depth, cash-out timing, prevalence) are the calibrated parts; the
   rupee distributions are plausible rather than validated.
5. **Complaint delay is treated as exogenous.** In reality it correlates with victim
   archetype and fraud type; here it is set per scenario.

---

## Regenerating

```bash
cd backend
python -m app.simulator.generator
```

Writes `data/accounts.parquet`, `data/transactions.parquet`, `data/labels.parquet`,
`data/episodes.parquet`, and `data/summary.md` — the last of which contains the actual
realised distributions for the current seed, including the diurnal histogram, archetype
mix, channel mix, and a table of all 12 injected rings.

Roughly 292,000 transactions across 40,000 accounts and 50 exit nodes, in about 2 seconds.
`target_transactions` sets the size of the *background* layer; pass-through sweeps and ring
episodes are generated on top of it, so the emitted dataset is about a third larger.
