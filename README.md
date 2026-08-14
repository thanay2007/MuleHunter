# Chakravyuh

**Real-time financial fraud interdiction for India.**

When an Indian citizen is defrauded, the stolen money is immediately pushed through a
chain of **mule accounts** — real KYC-verified bank accounts rented or sold to fraud
syndicates. Money is split and forwarded through 3–10 layers within 60–90 minutes, then
exits the banking system as ATM cash, crypto, or a cross-border transfer. Once it exits,
it is unrecoverable.

Banks today freeze the single account named in the victim's complaint. RBI's
MuleHunter.AI classifies individual accounts as suspicious. Both are useful. Neither
answers the operational question:

> Given a fraud complaint at time T for amount M, across a network of thousands of
> accounts spanning multiple banks — **which specific set of accounts should be frozen,
> in what order, within the next 60 minutes, to maximise rupees recovered, subject to a
> hard budget on how many innocent accounts we are willing to freeze?**

That is not a classification problem. It is a **network interdiction** problem: choosing
a cut in a time-expanded flow graph that blocks maximum adversarial flow under a
cardinality and cost budget. **Detection is an input to this system, not its output.**

---

## Honesty statement — read this first

- **All data is synthetic.** There is no real bank data, no real PII, and no real account
  numbers anywhere in this repository. The transaction generator is a first-class
  deliverable and is open-sourced here alongside everything else.
- **The generator is calibrated to publicly reported I4C and RBI statistics** on layering
  depth, cash-out timing, and mule prevalence. Every calibration choice is cited or
  reasoned in `backend/app/simulator/README.md`. Where a number is an assumption rather
  than a citation, it is labelled as one.
- **This is decision-support for an inter-bank body** such as I4C's Cyber Fraud
  Mitigation Centre. It is not a deployed banking system and does not claim to be.
- **Cross-bank data sharing is the real deployment blocker**, not the modelling. Two
  viable paths are documented in [Deployment](#deployment-path): a neutral clearing body,
  or secure aggregation where banks contribute edge structure without exposing customer
  data.

We would rather state a limitation than have a judge find it.

---

## Quick start

Two commands, no Docker, no cloud, no API keys, no auth. Everything runs offline after
install.

```bash
# 1. install (once)
cd backend  && pip install -r requirements.txt
cd frontend && npm install

# 2. build the artifacts (once)
cd backend
python -m app.simulator.generator   # ~2s   -> data/*.parquet
python -m app.detect.train          # ~4min -> models/, data/detector_report.json
python -m app.eval.harness          # ~45min-> data/benchmark.json  (optional)

# 3. run
cd backend  && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

Then open <http://127.0.0.1:5173>.

On Windows, `.\run.ps1 setup | data | train | bench | dev` do the same thing.
On Linux/macOS the equivalent `make` targets are in the `Makefile`.

Only steps 1 and 2 need to complete before the demo runs. The benchmark is slow
because it replays 200 incidents under four policies twice over, and the
Evaluation tab tells you which command to run if it is missing rather than
showing an empty chart.

**PyTorch is optional.** The GNN tier needs `torch` and `torch-geometric`;
without them everything runs on LightGBM, which is the tier that ships anyway.
`pip install torch --index-url https://download.pytorch.org/whl/cpu` then
`pip install torch-geometric` if you want it.

**Reproducibility.** Every generator is driven from one master seed
(`backend/app/config.py`). Regenerating with the same seed produces byte-identical files,
and the same scenario produces the same freeze plan on every run. A demo that changes
between rehearsal and stage is a lost hackathon. (Note `hash()` is never used for
anything reproducible — Python salts string hashing per process, which silently
breaks exactly this guarantee.)

---

## Build status

| Phase | Component | State |
|---|---|---|
| 0 | Repo scaffold, config, health route, frontend shell | ✅ |
| 1 | Transaction simulator + ground-truth labels | ✅ |
| 2 | Graph store, fund tracing, feature engineering, DuckDB | ✅ |
| 3 | Detection: rules → LightGBM → GraphSAGE, ring clustering | ✅ |
| 4 | **Freeze-frontier interdiction solver** | ✅ |
| 5 | Operations console, flow canvas, WebSocket replay | ✅ |
| 6 | Evaluation harness (200 held-out incidents) | ✅ |
| 7 | Explainability drawer, README, polish | ✅ |

---

## Architecture

```
complaint (victim, amount, time)
        │
        ▼
┌─────────────────────┐
│  incident subgraph  │  forward-reachable set, 6h horizon, ≤5k nodes
│  (graphstore/)      │  + 1-hop context for false-positive realism
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  detection          │  rules │ LightGBM │ GraphSAGE  →  p_mule per account
│  (detect/)          │  Louvain ring clustering
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  propagation        │  200 Monte Carlo rollouts of where the money goes next
│  (interdict/)       │  cached — reused by every greedy iteration
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  FREEZE FRONTIER    │  CELF greedy over a monotone submodular objective,
│  (interdict/greedy) │  (1 − 1/e) approximation guarantee; CP-SAT for the
└─────────┬───────────┘  exact optimality gap on small incidents
          ▼
   ordered freeze plan  →  ranked accounts, timing, graded action, ₹ saved
```

### Why greedy is defensible

Each rollout splits the stolen money into **particles**, and each particle records the
path it took — which accounts it passed through, and the minute it left each one. A
particle is intercepted if any freeze on its path lands before it moves on. Writing
`e(a)` for how reliably an action stops a transfer,

```
R(S) = Σ_particles  value · weight · ( 1 − Π_{a ∈ S on path} (1 − e(a)) )
```

which is a probabilistic **weighted coverage** function: monotone and submodular in `S`.
Greedy therefore attains at least `(1 − 1/e) ≈ 0.632` of the optimum under the
cardinality budget `K`. Under the innocence budget it becomes a submodular knapsack,
where ratio-greedy alone has no bound — so the solver runs value-greedy, ratio-greedy and
best-single-item and returns the best, which restores `½(1 − 1/e)`.

That is the worst case. `interdict/exact_cpsat.py` formulates the same problem as an
integer program and solves it exactly on small incidents, so the Evaluation tab reports
the **measured** gap rather than only the guaranteed one.

**CELF lazy evaluation** is what makes it interactive. Marginal gains only ever shrink —
coverage grows as freezes are added, and issue times slip later as the plan lengthens —
so a stale gain is always a valid upper bound and most candidates never need
re-evaluating.

### Why the order of the plan matters

A freeze instruction takes time to reach the holding bank, and only a few go out at once.
The k-th freeze in the plan therefore lands minutes after the first and intercepts
strictly less money. Greedy does not pick a set and sort it — it picks each next freeze
knowing when that freeze would actually take effect.

### Graded response

Not every account gets a full freeze. `outbound_hold` (credits allowed, debits blocked)
and `step_up_verification` are lower-harm actions, and they are *less effective* —
0.88 and 0.55 against 0.98 — so choosing one is a real trade-off rather than a free win.
Squeeze the innocence budget and the solver visibly switches from full freezes to gentler
actions rather than simply freezing fewer accounts. On S1:

| Innocence budget `B` | Plan | Actions issued |
|---|---|---|
| 0.05 | 18 | 18 × step-up verification |
| 0.25 | 14 | 13 × full freeze, 1 × outbound hold |
| ≥ 0.50 | 25 | 25 × full freeze |

The cost of a freeze is `w · (1 − min(p_mule, 0.97)) · activity_weight · harm(action)`.
The 0.97 ceiling is deliberate: a well-fitted detector returns scores like 0.9999, which
would price the harm of freezing a real person at essentially zero. No model output
justifies that, and capping it is also what keeps the innocence budget a live constraint
instead of a decorative slider.

---

## Results

200 incidents, drawn **only** from rings held out of detector training
(`RING-01, RING-05, RING-09, RING-12` — one per typology). Freeze authority `K = 25`,
innocence budget `B = 2.0`. Every policy plans from identical inputs and is scored by
replaying the same recorded timeline.

| Policy | Recovery | Kept in system | Lost | Innocent frozen | Freezes used | p95 solve |
|---|---:|---:|---:|---:|---:|---:|
| Current practice (named account) | 2.7% | ₹18.3L | ₹3.94Cr | **0** | 1.0 | 0 ms |
| One hop downstream | 7.1% | ₹42.9L | ₹3.70Cr | 127 | 6.6 | 0 ms |
| Top-K classifier | 23.7% | ₹1.36Cr | ₹2.76Cr | 148 | 25.0 | 8 ms |
| **Chakravyuh** | **38.0%** | **₹2.24Cr** | **₹1.89Cr** | **5** | 11.1 | 1287 ms |

**Recovery is defined as a counterfactual**: rupees kept inside the banking system that
would otherwise have been cashed out, measured against a do-nothing replay of the same
incident. Freezing an account that was never going to move money cannot inflate it.

Three things in that table matter more than the headline percentage:

- **14× current practice.** 2.7% is roughly the real-world recovery rate, and it is what
  happens when you freeze the one account the victim can name.
- **5 innocent accounts, against 148 and 127.** Chakravyuh recovers 1.6× what a top-K
  classifier recovers *while freezing 30× fewer innocent people*. The comparison is not
  "we recover more"; it is "we recover more and do far less harm", and that is the
  difference between an optimiser and a longer list.
- **11.1 freezes per incident against a budget of 25.** It stops when more freezing stops
  being worth the harm. Top-K spends the whole budget every time because it has no way
  to know when to stop.

**Greedy optimality gap**: mean **0.03%**, worst observed **0.66%**, measured against
CP-SAT on 20 incidents solved exactly. The `(1 − 1/e)` bound permits 36.8%. Greedy is
effectively optimal on this problem class; the guarantee is the floor, not the result.

On the stage scenario **S1** specifically (₹15,00,000, reported after 42 minutes, against
a ring the detector has never seen), Chakravyuh keeps ₹8.24L of the ₹12.67L that would
otherwise have been cashed out — **5.3×** a top-K classifier, at zero innocent freezes.

### What the numbers do not say

- **Detection AUC-PR is ~0.99, and that is not the achievement it looks like.** The task
  is heavily conditioned: these accounts are already known to have received money traced
  from a live fraud complaint minutes earlier. That is a far easier problem than
  unconditioned mule detection, and these figures are **not** comparable to a standing
  detection system like MuleHunter.AI. It also supports the thesis — detection is close to
  solved *in this setting*, and the open problem is what to do about it in sixty minutes.
- **The rules baseline scores 0.048 AUC-PR** and flags thousands of accounts at ~12%
  precision. It is not a strawman we weakened; it fires overwhelmingly on legitimate
  high-velocity accounts — chit fund operators, travel agents, wholesale traders — who by
  construction move money in and out within minutes. No threshold fixes that.
- **Recovery falls to ~29% against an adaptive adversary** who reroutes blocked money to
  another account they control rather than giving up. That figure is reported next to the
  passive one in the Evaluation tab, because assuming a passive adversary is the most
  flattering assumption available and it should not pass unstated.
- **Nothing recovers money reported six hours late.** The recovery-vs-delay curve shows
  exactly where the cliff is. That is the most useful output of this project for policy.

---

## Repository layout

```
backend/
  app/
    config.py          every tunable in the system, in one place
    api/               health, scenarios, graph, interdict, account,
                       evaluate, ws_replay, session (incident cache)
    simulator/         population, typologies, generator, scenarios
    graphstore/        build, trace (fund tracing), features, incidents,
                       warehouse (DuckDB)
    detect/            baseline_rules, gbdt, gnn, rings, explain, train
    interdict/         propagate, greedy, exact_cpsat, policies, replay
    eval/              harness, metrics, external (transfer test)
  tests/               phase acceptance tests + API contract tests
frontend/
  src/
    theme/tokens.ts    design tokens (mirrored into tailwind.config.ts)
    store/console.ts   Zustand: what the operator chose
    hooks/             useReplayStream (server-driven clock)
    components/        graph, console, inspect, eval
    routes/            Console, Rings, Evaluation, Data
```

### API

```
GET  /api/health                          artifact state, live
GET  /api/scenarios                       the six seeded incidents
GET  /api/graph/{scenario_id}             nodes, links, layout seed
POST /api/interdict                       freeze plan + replayed outcome
GET  /api/account/{id}?scenario_id=...    features, SHAP, marginal recovery
GET  /api/rings/{scenario_id}             communities found in this incident
GET  /api/evaluate                        benchmark.json
GET  /api/detector                        detector_report.json
WS   /ws/replay/{scenario_id}?policy=...  per-minute frames, both timelines
POST /api/intake                          file an arbitrary complaint
GET  /api/freeze-order/{id}               plan grouped by holding bank
GET  /api/freeze-order/{id}.pdf           the issued memorandum
```

`POST /api/intake` takes any account in the dataset, any amount and any pair of
times, and runs the same tracing, scoring, rollout and solve the six seeded
scenarios use — the resulting incident is addressable by every route above, so
the demo scenarios are demonstrably not hardcoded. `/api/freeze-order` returns
the plan grouped by holding bank, because eight institutions each act only on
their own accounts; the PDF is byte-identical for identical inputs.

The replay socket carries *both* timelines in every frame — do-nothing on one side,
Chakravyuh on the other — so the split comparison on the console is two views of one
computation rather than two computations that might disagree. The server owns the clock;
the client animates between frames but never invents them.

---

## Judge questions, and where the UI answers them

| Question | Where |
|---|---|
| Isn't this just MuleHunter.AI? | Evaluation → policy table. Both Chakravyuh and top-K use the *same* detector scores. Detection is an input. |
| How many innocent people did you freeze? | Ledger inset, headline figure on both sides. 5 vs 148 across the benchmark. |
| What if the classifier is wrong? | Innocence-budget slider on the console. Tighten it and the actions visibly change, not just the count. |
| Is your data real? | Data tab + `simulator/README.md`. Synthetic, calibrated, with the hard-negative contrast check printed. |
| Does it run fast enough? | Evaluation → p50/p95 solver latency, and the solve time on every console run. |
| How do you know greedy is good enough? | Evaluation → measured CP-SAT gap (0.03%) next to the `(1 − 1/e)` bound (36.8%). |
| Why would banks share data? | Deployment path, below. Secure aggregation needs topology and timing, never identity. |
| What's the single most important variable? | Evaluation → recovery-vs-complaint-delay curve. |

## Deployment path

The modelling is the easy part. The blocker is that no single bank can see the whole
graph, and the graph is where the signal lives.

1. **Neutral clearing body.** I4C's Cyber Fraud Mitigation Centre already sits between
   banks for complaint routing. Extending it to hold transaction edge structure during an
   active incident window is an institutional change, not a technical one.
2. **Secure aggregation / federated computation.** Banks contribute edge structure —
   which pseudonymous node sent how much to which other node, and when — without exposing
   customer identity. The interdiction solver only needs topology, amounts, and timing.
   It never needs to know whose account it is until a freeze order is actually issued,
   at which point the owning bank resolves the identifier itself.

Path 2 is the one worth building toward, because it does not require banks to trust each
other — only to trust the aggregation protocol.

---

## Limitations

Stated plainly, because a judge who finds one you did not mention discounts everything
else on the page.

1. **Synthetic data.** The generator is calibrated to public I4C/RBI reporting on layering
   depth, cash-out timing and mule prevalence, but calibration is not validation. Nothing
   here has met a real mule ring. The honest claim is that the *method* is sound and the
   evaluation is internally consistent — not that 38% would hold in production.
2. **The propagation model assumes the ring reuses its accounts.** It forecasts where
   money will go from where it has gone before. That is true of the syndicates in this
   dataset and broadly true of reported real ones, but a ring that burns its accounts
   after a single run would degrade the forecast badly. The solver would still work; it
   would just be planning against a worse prior.
3. **Freeze effectiveness is assumed, not measured.** 0.98 / 0.88 / 0.55 for the three
   actions are reasoned estimates in `config.py`, not observed rates. They are the single
   most load-bearing unvalidated numbers in the system.
4. **Taint tracing uses pro-rata pooling.** Once stolen funds mix with an account's own
   money, no rupee leaving is identifiably stolen, so outflow is tainted in proportion to
   tainted inflow. This is a standard AML convention and it is a *convention* — a
   different rule (last-in-first-out, for instance) would attribute differently.
5. **The adversary model is shallow.** Rerouting to a known counterparty is one adaptation.
   A real syndicate also recruits fresh accounts, shifts to a different rail, or simply
   moves faster once it learns the response time. None of that is modelled.
6. **No identity resolution, no KYC linkage, no cross-border leg.** The graph stops at the
   exit node.
7. **No external validation has been run yet.** Every number on this page is measured on
   data this repository generated, which is the weakest form of evidence available. The
   transfer harness is written and works — `python -m app.eval.external <transactions.csv>`
   normalises an [IBM AMLSim](https://github.com/IBM/AMLSim/) export and scores against it
   — but AMLSim ships parameter files rather than generated data, and the pre-generated
   Kaggle export needs an API token, so **the number has not been produced**. It is stated
   as an open item rather than quietly omitted.

   One thing the harness already makes clear, and it is worth saying in advance: a foreign
   transaction log carries no device fingerprints, no dormancy history, no KYC tier and no
   taint share. Several of the features carrying this detector are simply absent over
   there, so the transferable part of the signal is structural — fan-out and forwarding
   speed — and a transfer score measures that, not this model. Expect it to be much worse
   than 0.99, and expect that to be the honest and interesting result.

## License

Synthetic data and all source code released for evaluation purposes.