# MODELS.md — what the four systems actually are

Phase 1 discovery for the MuleHunter Bench harness. Written by reading each
repository, not by reading its README claims. Everything downstream — adapters,
environments, translators, the leakage audit — depends on this being right, so
where something could not be established it says so instead of guessing.

Read this alongside [`NOTICE`](../NOTICE), which records authorship and the
licensing position for each third-party project.

---

## Summary table

| | `mulehunter` (ours) | `argus_prism` | `mule_hunter_gnn` | `poc_isoforest` |
|---|---|---|---|---|
| Granularity | account | account | account (node) | account |
| Score kind | continuous | continuous | continuous | continuous + binary |
| Mode | streaming | streaming | batch-by-design, run streaming | streaming |
| Native explainer | SHAP (exact) | SHAP (exact) | none — rule list only | additive score terms |
| Ships weights | yes | yes | yes | yes |
| Weights usable on our data | yes | no (domain) | no (node ids) | no (domain) |
| Retrained by us | no | yes | yes | yes |
| License | this repo | **none found** | **none found** | **none found** |

---

## 1. `mulehunter` — ours

| Field | Value |
|---|---|
| **Path** | `backend/` |
| **Language / runtime** | Python ≥3.11 (developed on 3.13) |
| **Entrypoints** | `app.detect.gbdt.load_detector()` → `.score(FeatureMatrix)`, `.shap(FeatureMatrix)`; training via `python -m app.detect.train` |
| **Dependency manifest** | `backend/requirements.txt`, `backend/pyproject.toml` |
| **Model artifacts** | `backend/models/gbdt.txt` (LightGBM booster), `backend/models/detector.json` (isotonic calibration + feature order), `backend/models/gnn.pt` (second tier, not used by this harness) |
| **Trained on** | Incidents drawn from rings **outside** `settings.holdout_ring_ids`. The four held-out rings — one per typology, including RING-01, which is the stage demo — were never seen. |
| **Input format** | A list of account ids, a victim, and a cut-off timestamp. `app.graphstore.features.build_features` computes 37 features from transactions at or before the cut-off. |
| **Output format** | Isotonically calibrated probability per account, plus per-feature SHAP contributions. |
| **Granularity** | Accounts, scored *at a moment*. The same account scored at two times gives two different answers, which is the only way it is ever used. |
| **Score type** | Continuous, calibrated. |
| **Batch vs streaming** | Streaming. `build_features(accounts, victim, until)` is a pure function of the events visible at `until`. |
| **Explainability** | Native and exact: LightGBM `pred_contrib`. |
| **Randomness** | `settings.master_seed = 20260814` drives the train/calibration split and the betweenness pivot sample. LightGBM bagging is seeded through it. No unseeded RNG found. |
| **Author's recommended config** | `settings.gbdt_params` in `backend/app/config.py`. Used unchanged. |
| **License** | This repository. |

**Leakage audit.** The shipped weights are usable as-is: the benchmark test split
is the four held-out rings, and the training script excludes them by ring id
before building a single feature row. Verified in `app/detect/train.py` and
re-asserted by `bench/tests/test_no_leakage.py`.

---

## 2. `argus_prism` — ARGUS-PRISM WarmthScore

| Field | Value |
|---|---|
| **Path** | `ARGUS-PRISM-main/ARGUS-PRISM-main` |
| **Language / runtime** | Python ≥3.11. The *scoring engine* needs only `numpy` and `xgboost`; the rest of the backend (Postgres, Neo4j, Redis, JOSE, reportlab) is API plumbing the harness never touches. |
| **Entrypoints** | `app.engines.warmthscore.features.extract(ScoreInput) -> dict`, `.vector(ScoreInput) -> list[float]`; `app.engines.warmthscore.model.get_model().predict(row) -> (prob, shap)`; `app.engines.warmthscore.signals.raw_signals()` for the rule fallback. Training: `python -m warmth.train --n 12000 --seed 42 --rounds 400` from `ml-models/`. |
| **Dependency manifest** | `backend/pyproject.toml` (full API) and `ml-models/requirements.txt` (`xgboost>=2.1`, `scikit-learn>=1.5`, `numpy>=1.26`) — the second is what the harness installs. |
| **Model artifacts** | `backend/app/engines/warmthscore/artifacts/warmth_xgb.json` (+ `_features.json`, `_metrics.json`), duplicated in `ml-models/artifacts/`. Reported: AUC 0.9808, precision 0.9874, recall 0.9702, decision threshold 0.325. |
| **Trained on** | Their own synthetic generator, `ml-models/warmth/dataset.py`, 12,000 accounts, seed 42. Nothing to do with our data. |
| **Input format** | `ScoreInput(segment, last_active, opened_at, transactions=[TxnFeature(ts, amount, direction, channel)], device_imeis, sim_swaps_72h, dormant_reactivated_new_device)`. 23 features in a fixed order — six signal scores plus transaction aggregates, device count, SIM-swap count, dormancy, age, segment code. |
| **Output format** | Probability in [0,1] plus a per-feature SHAP contribution in log-odds. |
| **Granularity** | Accounts. |
| **Score type** | Continuous. (A rule-based fallback scorer exists with weights summing to 100; the harness uses the trained model, which is their stronger path.) |
| **Batch vs streaming** | Streaming. Every feature is a function of the transaction list handed in, so truncating that list to `t` is exactly the right semantics. |
| **Explainability** | Native and exact: XGBoost `pred_contribs`. |
| **Randomness** | `train.py` sets `random_state=7` on both splits. Their XGBoost params set no `seed`, so XGBoost's default (0) applies — deterministic but not varied. For the 5-seed protocol the harness passes an explicit `seed` and varies the split `random_state`, and records that this is a harness addition. |
| **Author's recommended config** | The exact params in `ml-models/warmth/train.py`: `max_depth 5`, `eta 0.1`, `subsample 0.85`, `colsample_bytree 0.85`, `min_child_weight 3`, `tree_method hist`, 400 rounds with early stopping at 40. Used unchanged. |
| **License** | **No LICENSE, NOTICE or COPYING file in the repository.** See NOTICE for how the harness handles this. |

**Leakage audit → retrain.** Their shipped booster was fitted on their own
synthetic universe. There is no overlap with our test split, so this is not a
leakage problem — it is a domain problem, and scoring our accounts with a model
fitted to somebody else's generator would understate them badly. The harness
therefore **retrains their model on our `train` split using their own training
code and their own hyperparameters**, and keeps their feature extraction
verbatim. Recorded as `retrained_by_us: true`,
`retrain_reason: "shipped weights fitted on the authors' own synthetic generator; domain mismatch with our accounts"`.

**Fields their schema cannot hold** (see `reports/input_parity.md`): IP-prefix
sharing, recipient-set overlap, graph topology of any kind, and cash-out
adjacency. Their `sim_swaps_72h` has no source in our data and is passed as 0 in
every case, which costs them their S6 signal — 10 of the rule scorer's 100
points, and one of 23 model features. That is a capability they have and this
benchmark cannot exercise; it is not evidence against them.

---

## 3. `mule_hunter_gnn` — MULE_HUNTER / alertixAI graph model

| Field | Value |
|---|---|
| **Path** | `MULE_HUNTER-main/MULE_HUNTER-main/ai-engine` (the repo brands itself *alertixAI* in its README; the folder and package names say MULE_HUNTER, and the harness uses the folder name) |
| **Language / runtime** | Python 3.11. Also contains a Java 17 / Spring Boot orchestrator, a Next.js control tower, and MongoDB — none of which are part of the model. |
| **Entrypoints** | `feature_engineering.build_graph_data()` → `shared-data/processed_graph.pt`; `train_model.train()` → `mule_model.pth`; `inference_service.py` (FastAPI) for serving. |
| **Dependency manifest** | `ai-engine/requirements.txt`, **UTF-16 encoded**, and headed "DO NOT pip install -r requirements.txt directly — install in order". Pins `torch==2.3.1`, `torch-geometric==2.5.3`, `pandas==2.2.2`, `numpy==1.26.4`, `scikit-learn==1.5.1`, `networkx==3.3`. `torch-scatter` / `torch-sparse` are listed as a separate wheel-index install; the layers actually used (`SAGEConv`, `GATConv`, `BatchNorm`) do not require them. |
| **Model artifacts** | `shared-data/mule_model.pth` (state dict), `processed_graph.pt`, `nodes.csv` (25 columns), `transactions.csv`, plus `eif_model.pkl` / `eif_scaler.pkl` for a separate Extended-Isolation-Forest service. `norm_params.json` is **not** checked in although the loader expects it. |
| **Trained on** | Their `data_generator.py` corpus. Node ids are composites of the form `10000_mastercard_debit` — one node per (account, card product), not per account. |
| **Input format** | `nodes.csv` with 21 feature columns in a fixed order (`FEATURE_COLS`, "ORDER IS CONTRACT") plus `is_fraud`; `transactions.csv` with `source,target,amount`. |
| **Output format** | `log_softmax` over two classes; class-1 probability is the mule score. |
| **Granularity** | Nodes. Because their node id is (account × card product), a translator must decide the mapping; ours emits **one node per account**, which is the identity mapping for our data and does not disadvantage them. |
| **Score type** | Continuous. |
| **Batch vs streaming** | **Batch by design** — the GNN needs the whole graph up front. The harness runs it *streaming anyway*, by rebuilding the observation graph from scratch at every tick and re-running message passing. That is more work and more charitable than recording a batch decision at window close, and it is recorded as `mode: "batch"` with `run_as: "streaming (graph rebuilt per tick)"` so the Arena badge is honest either way. |
| **Explainability** | **No native attribution for the GNN.** `inference_service.RISK_FACTOR_RULES` is a list of ten threshold rules over the input features that produces human-readable risk factors; the harness uses those as the native explainer where they fire and falls back to permutation importance over their 21 features otherwise. |
| **Randomness** | Seeds set in both `feature_engineering.py` and `train_model.py` (`torch`, `numpy`, `random` = 42; `cudnn.deterministic = True`; a locally seeded `torch.Generator` for the split). Ring detection is wall-clock-bounded (`RING_TIMEOUT_SEC`), which makes it **machine-dependent**: a slower machine finds fewer rings. The harness pins ring detection to a node budget instead of a time budget and records the substitution. |
| **Author's recommended config** | `HIDDEN_CHANNELS 128`, SAGE→GAT(4 heads)→SAGE + residual, weighted NLL loss, AdamW lr 1e-3 wd 1e-4, ReduceLROnPlateau, warm-up 150 epochs, patience 30 checks × 10 epochs, threshold tuned for best F1 on their val mask. Used unchanged. |
| **License** | **No LICENSE, NOTICE or COPYING file in the repository.** |

**Leakage audit → retrain.** Their weights are bound to their own node
vocabulary, so they cannot score our accounts at all. Retrained on our `train`
split with their training code and their hyperparameters.
`retrain_reason: "shipped weights are keyed to the authors' own node ids and cannot address our accounts"`.

**A serving-layer caveat we deliberately do not hold against them.**
`inference_service._transaction_adjusted_risk` applies hard score floors by
transaction amount — ₹1L → at least 0.45, ₹10L → 0.60, ₹1Cr → 0.72 — under the
comment *"A 2-crore transaction being scored 0.01 is a demo killer."* Those
floors are in their demo serving path, not in their model, and they are
transaction-level while this benchmark is account-level. The harness scores with
the model's account probability and leaves the floors out. Applying them would
have raised their score on exactly the large-amount cases this benchmark is made
of, so this choice is *against* our interest and is recorded as such.

**Fields their schema cannot hold**: KYC tier, dormancy break, device/IP
fingerprints as identifiers (they carry `device_mobile` and `device_consistency`
as scalars, not as a sharing graph). Their `community_fraud_rate` and
`second_hop_fraud_rate` are computed in their pipeline from the `is_fraud`
column of neighbouring nodes, which is not available at inference time; the
harness supplies a **watchlist of accounts already known to be mules from
training rings**, which is what a deployed instance would actually have.

---

## 4. `poc_isoforest` — Mule Account Detection POC

| Field | Value |
|---|---|
| **Path** | `mule-account-detection-poc-main/mule-account-detection-poc-main` |
| **Language / runtime** | Python. No version pinned anywhere. |
| **Entrypoints** | `train_model.py` — a **top-to-bottom script with no functions**, so it cannot be imported; the harness runs its logic in a runner that reproduces the script step for step. `dashboard.py` is Streamlit and is not part of scoring. |
| **Dependency manifest** | `requirement.txt` (note the singular filename; their README calls it `requirements.txt`): `pandas`, `numpy`, `scikit-learn`, `networkx`, `streamlit`, `plotly`, `joblib`. No versions pinned. |
| **Model artifacts** | `mule_model.pkl` (IsolationForest), `scaler.pkl` (StandardScaler), `mule_predictions.csv`. |
| **Trained on** | Their `generate_data.py` output — 200 accounts, 5,000 transactions, 12% mule prevalence. |
| **Input format** | `accounts.csv` = `account_id, account_age_days, kyc_risk (int 1..4), shared_device_count, is_mule`; `transactions.csv` = `sender, receiver, amount, timestamp`. |
| **Output format** | Two things, and the distinction matters: `mule_prediction` ∈ {0,1} from `IsolationForest.predict`, and a continuous `risk_score = shared_device_count·10 + velocity_score·100 + network_score·200` that their dashboard sorts by. |
| **Granularity** | Accounts. |
| **Score type** | Continuous for the ranking (`risk_score`); the IsolationForest output on its own is **binary**. The harness ranks by `risk_score` — their own choice — and uses `contamination=0.12` as their **native operating point**, since it is a published threshold. |
| **Batch vs streaming** | Streaming. Every input is a simple aggregate over transactions ≤ t plus static account fields. |
| **Explainability** | No SHAP, no feature importances. But `risk_score` is a sum of three named terms, which is an exact additive decomposition — better than a surrogate. The harness reports those three terms as the attribution and marks `attributions_available: true, attribution_source: "native additive terms"`. |
| **Randomness** | `IsolationForest(random_state=42)`. `generate_data.py` mixes seeded `numpy` with **unseeded `random.random()`** for the mule flag, so their own dataset is not reproducible — irrelevant here, since the harness trains on our data, but recorded because it is exactly the kind of thing this document exists to catch. |
| **Author's recommended config** | `contamination=0.12`, `random_state=42`, the seven features and the risk-score weights as written. `kyc_risk` is an integer 1–4 with no stated mapping; ours is `full→1, video→2, small→3, none→4` (weaker verification scores higher), documented in the adapter. |
| **License** | **No LICENSE, NOTICE or COPYING file in the repository.** |

**Leakage audit → retrain.** Their IsolationForest was fitted on 200 of their own
synthetic accounts. Retrained on our `train` split with their code and their
hyperparameters. `retrain_reason: "shipped weights fitted on 200 accounts from the authors' own generator"`.

---

## Cross-cutting findings

1. **None of the three third-party repositories carries a licence.** Absent an
   explicit grant, default copyright applies: we may read them and describe them,
   but we do not redistribute their source or their weights, and nothing from
   them is vendored into this repository. Each is referenced by path and by its
   authors' own project name. If any author objects, the harness's `--blind` mode
   already renders the whole comparison as System A–D with identical numbers.
2. **Three of the four ship weights that cannot be used on our data** — two for
   domain reasons and one because its node vocabulary is its own. All three are
   retrained here with their own code and their own hyperparameters. This is the
   check that cuts against us as often as for us, and it is the one most
   benchmarks skip.
3. **Only two of the four expose a real attribution.** Ours and ARGUS-PRISM both
   give exact SHAP. The PoC gives an exact additive decomposition. The GNN gives
   nothing, and the Arena's inspector says so rather than inventing a reason.
4. **One competitor's pipeline has a wall-clock-bounded step** (ring detection).
   Left alone it would make their score depend on how fast the benchmark machine
   is. Replaced with a node budget; recorded.
5. **Two competitors need a "known fraud" signal at inference time** that would
   not exist in production. Both are given a watchlist built from training rings
   only, so held-out rings genuinely start cold — for them and for us.
