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
    version: str = "0.1.0"
    phase: int = 0
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
    def duckdb_path(self) -> Path:
        return self.data_dir / "chakravyuh.duckdb"

    @property
    def benchmark_path(self) -> Path:
        return self.data_dir / "benchmark.json"

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
    target_transactions: int = 250_000

    # Simulation window. Transactions are generated across this many days of
    # background activity; incidents are injected into the final day.
    sim_days: int = 30

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
            "legit_high_velocity": 1.40,
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

    salary_day_multiplier: float = 3.2  # 1st-3rd of month
    festival_day_multiplier: float = 2.1

    # ------------------------------------------- phase 1: mule ring injection
    n_rings: int = 12  # 3 of each of the 4 typologies

    # Fan-out layering
    fanout_splits: tuple[int, int] = (6, 14)      # splits per layer
    fanout_layers: tuple[int, int] = (3, 7)       # depth
    fanout_delay_seconds: tuple[int, int] = (120, 540)  # 2-9 min between hops

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

    # Shared-infrastructure signal strength (the thing that beats per-account
    # rules). These are the ring tells the GNN is meant to learn.
    device_cluster_size: tuple[int, int] = (4, 10)
    ring_open_window_days: int = 21          # accounts opened close together
    dormancy_months: tuple[int, int] = (4, 14)  # dormant before activation

    # ---------------------------------------------- phase 2: graph & features
    incident_horizon_hours: int = 6
    incident_max_nodes: int = 5_000
    incident_context_hops: int = 1  # 1-hop context for false-positive realism

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

    train_rings: int = 8   # rings used for training
    holdout_rings: int = 4  # rings held out for honest evaluation

    louvain_resolution: float = 1.0
    shared_infra_edge_weight: float = 2.5  # device/IP edges in the projection

    # Baseline rule thresholds -- deliberately mirrors current bank practice.
    rule_dormancy_days: int = 90
    rule_single_credit_inr: float = 100_000.0
    rule_fanout_count: int = 5
    rule_fanout_window_minutes: int = 10

    # -------------------------------------------------- phase 4: interdiction
    time_step_minutes: int = 1  # time-expanded graph discretisation
    n_rollouts: int = 200       # Monte Carlo forward simulations

    default_budget_k: int = 12          # freeze authority budget
    default_innocence_budget: float = 2.0  # expected innocent freezes allowed
    w_innocence: float = 1.0            # cost scaling on (1 - p_mule)

    # Graded response thresholds on p_mule. Below the lowest, take no action.
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

    # Realistic per-window exit capacities, used as SINK edge capacities.
    atm_withdrawal_cap_inr: float = 25_000.0    # per card per day, typical
    exchange_deposit_cap_inr: float = 200_000.0
    crossborder_cap_inr: float = 500_000.0

    # CP-SAT exact solver only runs on graphs small enough to be tractable.
    cpsat_max_nodes: int = 800
    cpsat_time_limit_seconds: float = 20.0

    # Greedy solver performance target. Exceeding this is a demo-breaking bug.
    greedy_latency_budget_ms: int = 2_000

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

    # -------------------------------------------------------- phase 5: replay
    replay_fps: int = 12  # WebSocket frames per second
    replay_minutes: int = 180  # simulated minutes streamed per incident

    # ------------------------------------------------------------------ misc
    log_level: Literal["debug", "info", "warning", "error"] = "info"


settings = Settings()
