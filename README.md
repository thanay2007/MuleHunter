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

# 2. generate the dataset (once, ~60s)
cd backend && python -m app.simulator.generator

# 3. run
cd backend  && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

Then open <http://127.0.0.1:5173>.

On Windows, `.\run.ps1 setup`, `.\run.ps1 data`, `.\run.ps1 dev` do the same thing.
On Linux/macOS the equivalent `make` targets are in the `Makefile`.

**Reproducibility.** Every generator is driven from one master seed
(`backend/app/config.py`). Regenerating with the same seed produces byte-identical files,
and the same scenario produces the same freeze plan on every run. A demo that changes
between rehearsal and stage is a lost hackathon.

---

## Build status

| Phase | Component | State |
|---|---|---|
| 0 | Repo scaffold, config, health route, frontend shell | ✅ done |
| 1 | Transaction simulator + ground-truth labels | ✅ done |
| 2 | Graph store, feature engineering, DuckDB | ⬜ next |
| 3 | Detection: rules → LightGBM → GNN, ring clustering | ⬜ |
| 4 | **Freeze-frontier interdiction solver** | ⬜ |
| 5 | Operations console, flow canvas, replay | ⬜ |
| 6 | Evaluation harness (200 incidents) | ⬜ |
| 7 | Explainability drawer, polish | ⬜ |

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

**Why greedy is defensible.** Recovered rupees `R(S)` is a coverage-style objective over
a fixed set of cached rollouts, and is therefore monotone submodular. Greedy maximisation
under a cardinality constraint achieves a `(1 − 1/e) ≈ 0.63` approximation of the
optimum. This is a proven bound, not a hope — and the CP-SAT solver measures the actual
empirical gap on incidents small enough to solve exactly.

**Graded response.** Not every account gets a full freeze. `outbound_hold` (inbound
allowed, outbound blocked) and `step_up_verification` are lower-harm actions the solver
prefers for accounts with mid-range `p_mule`. Freezing an innocent person's account is a
real harm, and the objective prices it explicitly.

---

## Repository layout

```
backend/
  app/
    config.py          every tunable in the system, in one place
    api/               health, scenarios, graph, interdict, evaluate, ws_replay
    simulator/         population, typologies, generator, scenarios
    graphstore/        build, features, time-expansion
    detect/            baseline_rules, gbdt, gnn, rings, explain
    interdict/         propagate, greedy, exact_cpsat, policies
    eval/              harness, metrics
  tests/
frontend/
  src/
    theme/tokens.ts    design tokens (mirrored into tailwind.config.ts)
    components/        graph, console, inspect, eval
    routes/            Console, Rings, Evaluation
```

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

## License

Synthetic data and all source code released for evaluation purposes.