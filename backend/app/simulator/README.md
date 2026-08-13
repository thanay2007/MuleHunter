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

1. **Hard negatives are 8% of the population by construction.** Legitimate high-velocity
   accounts (chit fund operators, travel agents, wholesale traders) move money in and out
   within minutes with high fan-out. They are behaviourally almost identical to layering
   mules and are guaranteed never to be labelled as mules.
2. **The tells are noisy, not exclusive.** Device sharing, ATM withdrawal and high
   in-degree all occur in the legitimate population at meaningful rates. If only mules
   shared devices, `device_cluster_size` alone would solve the problem and every
   downstream metric would be meaningless.
3. **Four structurally different typologies.** A detector tuned to fan-out width misses
   chain-and-burst; one tuned to large transfers misses structuring by construction.

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
| **Fan-out layering** | Collector splits 6–14 ways, 3–7 layers deep, 2–9 min per hop | Nothing — this is the classic case |
| **Chain-and-burst** | Narrow chain (fan-out 1–2) for 4 hops, then bursts 8–16 wide | Fan-out threshold rules |
| **Structuring** | Every transfer held in ₹45,000–49,900, many parallel paths | ₹50,000 reporting-threshold rules |
| **Crypto exit** | 2–3 hops, terminates at a few shared exchange deposit accounts | Depth-based heuristics |

Ring size is capped at 28–120 accounts. Unbounded branching would explode past any
realistic ring, so the size budget is allocated across the depth rather than compounded
freely. Reported syndicate rings run from a few dozen to a few hundred accounts.

### Shared infrastructure — the signal that beats per-account rules

This is the core modelling claim of the project, so it is worth being explicit about what
is injected:

- **4–10 accounts share one `device_fingerprint`**, in clusters within a ring.
- **Clusters share an `ip_prefix`.**
- **Accounts within a ring are opened within a 21-day window** — one recruiter opened them.
- **Accounts are dormant 4–14 months before activation** — the classic rented-account tell.
- **Recipient sets overlap** across accounts that look otherwise unrelated.

None of these is individually conclusive, and all of them occur in the legitimate
population at some rate. That is deliberate. The argument the product makes on stage —
*a rule engine sees N unrelated grey accounts, a graph model sees one organisation* —
only holds if the evidence is genuinely distributed across the neighbourhood rather than
sitting in any single node's features.

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

Each ring also runs 2–4 additional randomised episodes so the detectors have varied
training data rather than six examples.

---

## Known limitations

Stated plainly, because a judge will ask:

1. **Account balances are not modelled.** Transfers are generated from behavioural rates,
   not from a running balance with an overdraft constraint. This means a mule's
   "transferable amount" in the propagation model is an estimate from observed flow rather
   than a known cash position.
2. **Ring behaviour is stationary.** Real syndicates adapt to enforcement within days.
   Nothing here models an adversary responding to being interdicted, so the reported
   recovery numbers should be read as an upper bound against a *non-adaptive* opponent.
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

Writes `data/accounts.parquet`, `data/transactions.parquet`, `data/labels.parquet`, and
`data/summary.md` — the last of which contains the actual realised distributions for the
current seed, including the diurnal histogram, archetype mix, channel mix, and a table of
all 12 injected rings.
