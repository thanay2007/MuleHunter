"""Every tunable in the system lives here.

Rule for this repo: no magic numbers in modules. If a number changes behaviour,
it belongs in this file with a comment explaining why it has that value.

Values are grouped by the phase that consumes them. Anything marked CALIBRATED
is traceable to a publicly reported I4C/RBI figure and is justified in
`app/simulator/README.md` -- do not change those without updating that document,
because the honesty of the whole project rests on them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR: Path = Path(__file__).resolve().parent.parent
REPO_DIR: Path = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Central configuration object. Import the module-level `settings` instance."""

    model_config = SettingsConfigDict(
        env_prefix="CHAKRAVYUH_",
        env_file=".env",
        extra="ignore",
    )

    # ---------------------------------------------------------------- service
    version: str = "1.0.0"
    phase: int = 7
    service_name: str = "chakravyuh"
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    # ------------------------------------------------------------------ paths
    data_dir: Path = BACKEND_DIR / "data"
    models_dir: Path = BACKEND_DIR / "models"

    @property
    def accounts_path(self) -> Path:
        return self.data_dir / "accounts.parquet"

    @property
    def transactions_path(self) -> Path:
        return self.data_dir / "transactions.parquet"

    @property
    def labels_path(self) -> Path:
        return self.data_dir / "labels.parquet"

    @property
    def episodes_path(self) -> Path:
        return self.data_dir / "episodes.parquet"

    @property
    def duckdb_path(self) -> Path:
        return self.data_dir / "chakravyuh.duckdb"

    @property
    def benchmark_path(self) -> Path:
        return self.data_dir / "benchmark.json"

    @property
    def detector_path(self) -> Path:
        return self.models_dir / "gbdt.txt"

    @property
    def detector_meta_path(self) -> Path:
        return self.models_dir / "detector.json"

    @property
    def gnn_path(self) -> Path:
        return self.models_dir / "gnn.pt"

    @property
    def scores_path(self) -> Path:
        """Cached p_mule per account per incident. Keeps the API sub-second."""
        return self.models_dir / "scores.parquet"

    @property
    def behaviour_path(self) -> Path:
        """Fitted forward-transfer behaviour used by the propagation model."""
        return self.models_dir / "behaviour.json"

    @property
    def detector_report_path(self) -> Path:
        return self.data_dir / "detector_report.json"

    @property
    def summary_path(self) -> Path:
        return self.data_dir / "summary.md"

    # ------------------------------------------------------------ determinism
    # One master seed drives every generator in the system. The same scenario
    # must produce byte-identical output on every run, on every machine.
    master_seed: int = 20260814

    # ------------------------------------------------- phase 1: the simulator
    n_accounts: int = 40_000
    n_banks: int = 8
    #: Target for the *background* layer. Pass-through sweeps and ring episodes
    #: are generated on top of it, so the emitted dataset is roughly a third
    #: larger than this figure.
    target_transactions: int = 200_000

    # Simulation window. Transactions are generated across this many days of
    # background activity; scenario incidents are injected into the final day.
    # The window is anchored to a fixed end date so the dataset never depends
    # on the wall clock -- that would break byte-identical regeneration.
    sim_days: int = 30
    sim_end_date: str = "2026-08-10"

    # Background traffic is generated from the per-archetype rates below, then
    # scaled by a single global factor so the total lands on
    # `target_transactions`. The rates therefore set the *relative* activity of
    # each archetype (which is what detection depends on); the target sets the
    # absolute dataset size. See simulator/README.md.
    #
    # Most transfers go to a small set of repeat counterparties rather than to
    # a uniformly random account. This is what gives the graph real community
    # structure for Louvain to find, and makes recipient-set overlap a
    # meaningful signal.
    n_regular_counterparties: int = 8
    regular_counterparty_prob: float = 0.72
    same_district_prob: float = 0.55  # locality bias when picking counterparties

    # Salary credits come from a small pool of employer accounts, creating the
    # hub structure a real retail banking graph has.
    n_employers: int = 220
    salary_lognormal: tuple[float, float] = (10.4, 0.55)
    salary_days_of_month: tuple[int, ...] = (1, 2, 3)

    # Archetype shares. Must sum to 1.0 (asserted at generation time).
    # `legit_high_velocity` is the hard-negative class: chit fund operators,
    # travel agents, wholesale traders. They look like mules to a naive rule
    # engine and are what makes the detection problem non-trivial.
    archetype_shares: dict[str, float] = Field(
        default_factory=lambda: {
            "salaried": 0.42,
            "small_merchant": 0.18,
            "student": 0.12,
            "homemaker": 0.15,
            "hnw": 0.05,
            "legit_high_velocity": 0.08,
        }
    )

    # Log-normal transaction amount parameters (mu, sigma) on log(INR), per
    # archetype. CALIBRATED against typical retail UPI ticket sizes.
    amount_lognormal: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: {
            "salaried": (7.4, 1.05),
            "small_merchant": (6.2, 0.95),
            "student": (5.6, 0.85),
            "homemaker": (6.4, 0.90),
            "hnw": (10.2, 1.20),
            "legit_high_velocity": (9.1, 1.15),
        }
    )

    # Mean transactions per account per day, per archetype.
    daily_txn_rate: dict[str, float] = Field(
        default_factory=lambda: {
            "salaried": 0.16,
            "small_merchant": 0.85,
            "student": 0.34,
            "homemaker": 0.07,
            "hnw": 0.11,
            # High-velocity accounts mostly *forward* money rather than
            # initiate payments, so most of their volume comes from the
            # pass-through layer rather than from this rate.
            "legit_high_velocity": 0.45,
        }
    )

    # Indian diurnal activity curve: 24 hourly weights, IST. Peaks near 11:00
    # and 20:00. CALIBRATED to reported NPCI intraday UPI volume shape.
    diurnal_weights: list[float] = Field(
        default_factory=lambda: [
            0.10, 0.05, 0.03, 0.03, 0.04, 0.12,  # 00-05
            0.35, 0.70, 1.05, 1.45, 1.80, 2.05,  # 06-11
            1.85, 1.60, 1.50, 1.55, 1.70, 1.90,  # 12-17
            2.00, 2.15, 2.20, 1.60, 0.90, 0.35,  # 18-23
        ]
    )

    # Pass-through behaviour for the `legit_high_velocity` archetype: money in,
    # money straight back out, wide, within minutes. See
    # `population._add_passthrough_traffic` -- this is what makes the hard
    # negatives genuinely hard, and it is calibrated to sit on top of the mule
    # forwarding distribution rather than beside it.
    passthrough_prob: float = 0.72
    passthrough_fanout: tuple[int, int] = (3, 9)
    passthrough_delay_seconds: tuple[int, int] = (90, 1_500)  # 1.5-25 min
    passthrough_retained: tuple[float, float] = (0.03, 0.18)  # working margin

    salary_day_multiplier: float = 3.2  # 1st-3rd of month
    festival_day_multiplier: float = 2.1
    festival_dates: list[str] = Field(
        default_factory=lambda: ["2026-07-26", "2026-08-08"]
    )

    # Channel mix for background traffic. ATM withdrawal is deliberately a
    # normal thing legitimate people do -- if only mules used ATMs, cash-out
    # proximity would trivially solve the detection problem and the benchmark
    # would be meaningless.
    channel_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "UPI": 0.62,
            "IMPS": 0.14,
            "NEFT": 0.11,
            "CARD": 0.07,
            "ATM_WITHDRAWAL": 0.06,
        }
    )

    # A rented mule account still belongs to a real person, and it is still a
    # real account: after the syndicate activates it, ordinary traffic carries
    # on around the laundering runs at a reduced rate. This matters more than it
    # looks. With mules generating *no* ordinary traffic, "has no background
    # activity" separates them perfectly, every detector scores ~1.0, and the
    # benchmark measures nothing. It also gives the laundering graph edges into
    # the ordinary population, which is where false positives come from.
    #
    # Before activation the account is genuinely untouched -- that is the
    # dormancy break, and it is the one tell that survives.
    mule_background_rate_ratio: float = 0.30

    # Size of the device pool relative to the population. At 0.55 the average
    # handset carries roughly two accounts and a long tail carries five or six
    # -- families, shared shop phones, cyber cafes. Set this near 1.0 and
    # ordinary accounts never share a device, which turns "shares a device"
    # into a perfect mule detector and makes the whole detection problem
    # vacuous. Legitimate device sharing has to be common for the feature to be
    # a signal rather than a giveaway.
    legit_device_pool_ratio: float = 0.55

    # ------------------------------------------- phase 1: mule ring injection
    n_rings: int = 12  # 3 of each of the 4 typologies

    # Accounts per ring. Real syndicate rings reported by I4C run from a few
    # dozen to a few hundred accounts; a tree with unbounded fan-out and depth
    # would explode past that, so growth is capped by this budget.
    ring_size_range: tuple[int, int] = (60, 180)

    # Each ring launders money many times across the window. One episode per
    # scenario is pinned to the exact amount and time the scenario specifies;
    # the rest are randomised to give the detectors varied training data.
    #
    # A syndicate ring is a business: it runs continuously, not once. The range
    # is set so the four held-out rings alone supply enough distinct incidents
    # to fill the 200-incident benchmark without reusing training rings.
    ring_episodes_range: tuple[int, int] = (14, 20)

    # Exit infrastructure: where money leaves the banking system. These are
    # graph nodes, not retail accounts, and sit outside `n_accounts`.
    n_atm_exits: int = 40
    n_exchange_exits: int = 6
    n_crossborder_exits: int = 4

    # Fan-out layering. CALIBRATED: I4C describes money moving through 3-10
    # layers within 60-90 minutes. Depth and per-hop delay are set so a chain
    # takes most of that window rather than completing in ten minutes -- which
    # is what makes interdiction a live problem. If layering finishes before
    # anyone can complain, there is nothing to decide.
    fanout_splits: tuple[int, int] = (6, 14)      # splits per layer
    fanout_layers: tuple[int, int] = (4, 8)       # depth
    fanout_delay_seconds: tuple[int, int] = (180, 900)  # 3-15 min between hops

    # Chain-and-burst
    chain_narrow_hops: int = 4
    chain_narrow_fanout: tuple[int, int] = (1, 2)
    chain_burst_splits: tuple[int, int] = (8, 16)

    # Structuring: every transfer held just under the reporting threshold.
    structuring_threshold_inr: float = 50_000.0
    structuring_band_inr: tuple[float, float] = (45_000.0, 49_900.0)

    # Crypto exit
    crypto_hops: tuple[int, int] = (2, 3)
    crypto_exchange_accounts: int = 6  # shared across rings, high volume

    # Cash-out timing after victim credit. CALIBRATED: I4C reporting indicates
    # funds typically exit the banking system within 45-90 minutes.
    cashout_delay_minutes: tuple[int, int] = (45, 90)

    # Share of laundering hops that land on a genuinely legitimate account
    # rather than another ring member. Layering routes through real businesses
    # on purpose -- a payment to a real merchant is excellent cover, and the
    # merchant has no idea.
    #
    # This is what creates the innocence problem. Without it, every account
    # holding stolen money is a mule, freezing is free of collateral damage,
    # and the innocence budget is decoration. With it, some of the accounts
    # sitting on the victim's money belong to a shopkeeper who sold somebody a
    # phone, and freezing them is a real harm the solver has to price.
    laundering_legit_hop_prob: float = 0.14

    # Shared-infrastructure signal strength (the thing that beats per-account
    # rules). These are the ring tells the GNN is meant to learn.
    device_cluster_size: tuple[int, int] = (4, 10)
    ring_open_window_days: int = 21          # accounts opened close together
    dormancy_months: tuple[int, int] = (4, 14)  # dormant before activation

    # How *consistently* those tells appear. This is the most consequential
    # block of numbers in the simulator.
    #
    # With all three at 1.0 every mule carries every tell, the classes separate
    # perfectly, and both models score ~1.00 AUC-PR. That is not a good result,
    # it is a broken dataset -- and a judge reading 0.999 will assume leakage
    # and discount everything else on the page.
    #
    # Real syndicates are not uniform. Some accounts are bought while already
    # in use, so there is no dormancy break. Some are recruited later and opened
    # months apart. Careful operators use a separate handset per account. The
    # accounts carrying no individual tell at all are the interesting ones:
    # individually unremarkable, damning only through their neighbourhood, and
    # exactly the case a per-account model cannot reach.
    ring_device_share_prob: float = 0.55
    ring_dormancy_prob: float = 0.70
    ring_open_window_prob: float = 0.60

    # ---------------------------------------------- phase 2: graph & features
    incident_horizon_hours: int = 6
    incident_max_nodes: int = 5_000
    incident_context_hops: int = 1  # 1-hop context for false-positive realism

    # How far past the money's current position the solver is allowed to look
    # for accounts to freeze, along edges observed before the complaint. Three
    # hops is what lets a freeze land *ahead* of the money instead of chasing
    # it. It also drags in a large tail of ordinary accounts, which is the
    # point: the solver must reject them itself rather than be handed a
    # pre-filtered shortlist.
    candidate_hops: int = 3

    feature_windows_hours: list[int] = Field(default_factory=lambda: [1, 6, 24])
    night_hours: tuple[int, int] = (23, 5)  # inclusive start, exclusive end

    # ------------------------------------------------------ phase 3: detection
    gbdt_params: dict[str, float | int | str] = Field(
        default_factory=lambda: {
            "objective": "binary",
            "learning_rate": 0.05,
            "num_leaves": 63,
            "min_data_in_leaf": 40,
            "feature_fraction": 0.85,
            "bagging_fraction": 0.85,
            "bagging_freq": 1,
            "n_estimators": 400,
            "verbosity": -1,
        }
    )

    gnn_hidden_dim: int = 64
    gnn_layers: int = 2
    gnn_epochs: int = 120
    gnn_lr: float = 0.005
    gnn_dropout: float = 0.25
    gnn_aux_loss_weight: float = 0.3  # auxiliary layer_index head

    # Rings held out of detector training entirely: one of each typology, so the
    # held-out set exercises every laundering shape rather than three variants
    # of one. RING-01 is deliberately included -- it is scenario S1, the stage
    # demo, which means the demo runs on a ring the detector has never seen.
    # Anything else invites the obvious question and has no good answer.
    holdout_ring_ids: list[str] = Field(
        default_factory=lambda: ["RING-01", "RING-05", "RING-09", "RING-12"]
    )

    louvain_resolution: float = 1.0
    shared_infra_edge_weight: float = 2.5  # device/IP edges in the projection
    # A device or IP shared by more accounts than this is infrastructure, not a
    # syndicate -- a carrier NAT range, a default fingerprint. Linking every
    # pair inside such a group would merge unrelated communities into one blob.
    max_shared_infra_group: int = 25
    # Communities smaller than this are noise, not rings.
    min_ring_size: int = 4
    # Ring discovery runs over accounts the detector flagged, not every account
    # in reach -- clustering mostly-ordinary traffic measures nothing useful.
    ring_cluster_threshold: float = 0.5

    # Baseline rule thresholds -- deliberately mirrors current bank practice.
    rule_dormancy_days: int = 90
    rule_single_credit_inr: float = 100_000.0
    rule_fanout_count: int = 5
    rule_fanout_window_minutes: int = 10

    # -------------------------------------------------- phase 4: interdiction
    time_step_minutes: int = 1  # time-expanded graph discretisation
    n_rollouts: int = 200       # Monte Carlo forward simulations

    # The stolen amount is discretised into particles, each tracing one path
    # from the victim to wherever it ends up. Recovery then becomes weighted
    # maximum coverage over particles, which is monotone submodular -- that is
    # what earns the (1 - 1/e) guarantee. More particles means a finer estimate
    # and a slower solve; 240 x 200 rollouts keeps the whole solve under 2s.
    particles_per_rollout: int = 240
    # Hard stop on how far a parcel is walked forward. Real chains are 3-10
    # hops; this only exists so a pathological cycle cannot run forever.
    max_rollout_hops: int = 14

    # Relative value of securing money that was not going to escape anyway.
    #
    # The primary objective is money kept inside the banking system, because
    # money that leaves is gone and money that stays can still be returned.
    # But securing a parked ₹4,00,000 under a freeze is worth something too --
    # it is under bank control instead of merely sitting where the syndicate
    # left it. Weighting it below an intercepted leak keeps the solver's
    # priority right while stopping it from ignoring parked money entirely.
    #
    # The weighted objective is a non-negative combination of two coverage
    # functions, so it stays monotone submodular and the (1 - 1/e) bound holds.
    parked_money_weight: float = 0.2

    # Freeze authority: how many instructions can be issued for one incident.
    # A coordinated body sends these over an API to each holding bank, so the
    # binding limit is the appetite for collateral damage rather than the
    # clerical effort -- which is precisely what the innocence budget prices.
    default_budget_k: int = 25
    default_innocence_budget: float = 2.0  # expected innocent freezes allowed
    w_innocence: float = 1.0            # cost scaling on (1 - p_mule)

    # Ceiling on how certain the cost function is allowed to be.
    #
    # A well-fitted detector on this data returns scores like 0.9999, which
    # makes `1 - p_mule` about 1e-4 and the modelled harm of freezing that
    # account essentially zero. That is a statement about the model's
    # confidence, not about the world: models are wrong, the account belongs to
    # a real person, and no score justifies pricing that risk at zero.
    #
    # Capping the score used for costing puts a floor under the price of every
    # freeze. It is also what makes the innocence budget a live constraint
    # rather than a decorative slider.
    score_confidence_ceiling: float = 0.97

    # Graded response thresholds on p_mule. Below the lowest, take no action --
    # an account we barely suspect should not be touched at all.
    action_full_freeze_threshold: float = 0.80
    action_outbound_hold_threshold: float = 0.55
    action_step_up_threshold: float = 0.35

    # Relative harm weight of each action, used in the innocence cost. A
    # step-up verification on an innocent person is far cheaper than a freeze.
    action_harm_weight: dict[str, float] = Field(
        default_factory=lambda: {
            "full_freeze": 1.0,
            "outbound_hold": 0.45,
            "step_up_verification": 0.15,
        }
    )

    # How reliably each action actually stops an outbound transfer. This is the
    # reason graded response is a real trade-off rather than a free lunch: the
    # gentler the action, the more money slips through.
    #   full_freeze        - the rail is shut; effectively total.
    #   outbound_hold      - new debits blocked, but already-queued NEFT/card
    #                        authorisations still settle.
    #   step_up_verification - stops an operator who cannot pass re-KYC, and
    #                        merely inconveniences the genuine account holder.
    action_effectiveness: dict[str, float] = Field(
        default_factory=lambda: {
            "full_freeze": 0.98,
            "outbound_hold": 0.88,
            "step_up_verification": 0.55,
        }
    )

    # Operational reality: a freeze is not instantaneous. Each instruction takes
    # this long to reach the holding bank and take effect, and only so many can
    # be dispatched at once. This is what makes the *order* of the plan matter
    # rather than just its membership.
    freeze_issue_latency_minutes: float = 1.5
    freeze_parallel_dispatch: int = 4

    # An adaptive adversary. When a transfer is blocked, the operator may push
    # the money to a different account they control instead of giving up. Set to
    # 0.0 to assume a passive adversary; the benchmark reports both.
    adversary_reroute_prob: float = 0.35
    adversary_reroute_delay_minutes: tuple[int, int] = (3, 11)
    adversary_max_retries: int = 2

    # Realistic per-window exit capacities, used as SINK edge capacities.
    atm_withdrawal_cap_inr: float = 25_000.0    # per card per day, typical
    exchange_deposit_cap_inr: float = 200_000.0
    crossborder_cap_inr: float = 500_000.0

    # CP-SAT exact solver only runs on graphs small enough to be tractable.
    cpsat_max_nodes: int = 800
    cpsat_time_limit_seconds: float = 20.0

    # Greedy solver performance target. Exceeding this is a demo-breaking bug.
    greedy_latency_budget_ms: int = 2_000

    # Fund tracing. The solver never reads the `is_fraud` label -- it only sees
    # transactions up to the complaint time and traces the victim's money
    # forward pro rata, the way an AML analyst does. An account that received
    # 10% of its recent inflow from the victim carries 10% taint out on every
    # rupee it sends. Taint below this floor is dropped rather than chased
    # through the whole retail graph.
    taint_floor_inr: float = 250.0
    taint_min_share: float = 0.02

    # ------------------------------------------------------- phase 6: harness
    n_benchmark_incidents: int = 200
    benchmark_policies: list[str] = Field(
        default_factory=lambda: [
            "named_account_only",
            "top_k_classifier",
            "one_hop_downstream",
            "chakravyuh_greedy",
        ]
    )
    # Complaint delays swept in the recovery-vs-delay curve (minutes).
    benchmark_delay_grid: list[int] = Field(
        default_factory=lambda: [5, 10, 15, 30, 45, 60, 90, 120, 240, 360]
    )
    # Innocence budgets swept for the precision-recall trade-off curve.
    benchmark_innocence_grid: list[float] = Field(
        default_factory=lambda: [0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
    )
    # Incidents small enough to also solve exactly, for the optimality gap.
    benchmark_exact_incidents: int = 20
    # The delay and innocence curves replay each incident many times over, so
    # they run on a prefix of the benchmark rather than all of it.
    benchmark_curve_incidents: int = 24

    # -------------------------------------------------------- phase 5: replay
    replay_fps: int = 12  # WebSocket frames per second
    # How many incident contexts to keep hot. Each is a few MB; six covers all
    # the demo scenarios so nothing rebuilds mid-presentation.
    context_cache_size: int = 8

    # ------------------------------------------------------------------ misc
    log_level: Literal["debug", "info", "warning", "error"] = "info"


settings = Settings()
