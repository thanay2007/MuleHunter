/**
 * Typed API client. Every backend response has an explicit interface here --
 * `any` is banned by tsconfig and by taste.
 *
 * Requests are origin-relative; Vite proxies /api to the backend in dev.
 */

export interface ArtifactStatus {
  accounts: boolean
  transactions: boolean
  labels: boolean
  warehouse: boolean
  benchmark: boolean
}

export interface HealthResponse {
  status: string
  service: string
  version: string
  phase: number
  uptime_seconds: number
  master_seed: number
  artifacts: ArtifactStatus
}

export interface Scenario {
  scenario_id: string
  name: string
  summary: string
  victim_account: string
  victim_district: string
  victim_archetype: string
  amount_inr: number
  complaint_delay_minutes: number
  ring_id: string
  ring_typology: string
  secondary_ring_id: string | null
  incident_time: string
  complaint_time: string
  ring_accounts: number
  /** Fraud transfer value in the window, counted once per hop. Not a loss figure. */
  episode_flow_inr: number
  hops: number
}

export type NodeKind = 'victim' | 'mule' | 'legit' | 'exit'

export interface GraphNode {
  id: string
  kind: NodeKind
  bank_id: string
  district: string
  archetype: string
  is_mule: boolean
  ring_id: string
  layer_index: number
  is_cashout_node: boolean
  exit_kind: string
  depth: number
  first_seen_minute: number
  amount_in: number
  amount_out: number
  /** The victim's money that passed through this account. */
  tainted_in: number
}

export interface GraphLink {
  source: string
  target: string
  amount: number
  /** How much of this transfer was the victim's money. */
  tainted: number
  minute: number
  channel: string
  is_fraud: boolean
}

export interface IncidentGraph {
  scenario_id: string
  victim_account: string
  incident_time: string
  horizon_minutes: number
  layout_seed: number
  truncated: boolean
  fraud_flow_inr: number
  nodes: GraphNode[]
  links: GraphLink[]
}

export interface Ring {
  ring_id: string
  typology: string
  accounts: number
  banks: string[]
  districts: number
  device_clusters: number
  max_layer: number
  cashout_nodes: number
  total_flow_inr: number
  txn_count: number
  dormancy_days: number
}

export interface NamedCount {
  name: string
  count: number
}

export interface HourCount {
  hour: number
  count: number
}

export interface DatasetSummary {
  accounts: number
  exit_nodes: number
  transactions: number
  fraud_transactions: number
  mule_accounts: number
  mule_prevalence: number
  banks: number
  districts: number
  total_laundered_inr: number
  archetypes: NamedCount[]
  channels: NamedCount[]
  hourly: HourCount[]
}

export type PolicyId =
  | 'named_account_only'
  | 'top_k_classifier'
  | 'one_hop_downstream'
  | 'chakravyuh_greedy'

export type FreezeAction =
  | 'full_freeze'
  | 'outbound_hold'
  | 'step_up_verification'

export interface PlanStep {
  rank: number
  account_id: string
  bank: string
  issue_at_minute: number
  action: FreezeAction
  marginal_recovery_inr: number
  p_mule: number
  innocence_cost: number
  effectiveness: number
  reason_codes: string[]
  is_mule: boolean
}

export interface Outcome {
  /** Rupees kept inside the banking system that would otherwise have left. */
  prevented_inr: number
  leaked_inr: number
  secured_inr: number
  residual_inr: number
  already_gone_inr: number
  innocent_frozen: number
  mules_frozen: number
  blocked_transfers: number
  rerouted_transfers: number
}

export interface InterdictRequest {
  scenario_id: string
  policy: PolicyId
  budget_k: number
  innocence_budget: number
  adaptive_adversary: boolean
}

export interface InterdictResponse {
  scenario_id: string
  policy: PolicyId
  policy_label: string
  budget_k: number
  innocence_budget: number
  plan: PlanStep[]
  projected_recovery_inr: number
  projected_leak_inr: number
  projected_secured_inr: number
  innocent_accounts_frozen_expected: number
  total_innocence_cost: number
  solve_ms: number
  outcome: Outcome
  do_nothing_leak_inr: number
  amount_inr: number
  complaint_minute: number
  horizon_minutes: number
  candidates_considered: number
  rollouts: number
  particles: number
}

export interface Attribution {
  feature: string
  label: string
  plain: string
  value: number
  shap: number
  population_median: number
  direction: 'raises' | 'lowers'
}

export interface FeatureRow {
  feature: string
  label: string
  value: number
  population_median: number
  deviation: number
}

export interface Marginal {
  in_plan: boolean
  issued_at_minute: number | null
  saved_inr: number
  alternatives: { minute: number; saved_inr: number }[]
}

export interface AccountDetail {
  account_id: string
  scenario_id: string
  bank_id: string
  district: string
  archetype: string
  kyc_tier: string
  open_date: string
  p_mule: number
  activity_weight: number
  tainted_held_inr: number
  tainted_through_inr: number
  first_seen_minute: number | null
  is_mule: boolean
  ring_id: string
  layer_index: number
  is_cashout_node: boolean
  attributions: Attribution[]
  features: FeatureRow[]
  marginal: Marginal
  rule_flags: string[]
}

export interface DiscoveredRing {
  ring_id: string
  accounts: number
  banks: string[]
  districts: number
  device_clusters: number
  ip_clusters: number
  total_flow_inr: number
  cashout_capacity_inr: number
  mean_p_mule: number
  confidence: number
  dormancy_days_median: number
  members: string[]
}

export interface PolicySummary {
  policy: PolicyId
  n_incidents: number
  recovery_rate_mean: number
  recovery_rate_median: number
  prevention_rate_mean: number
  prevented_inr_total: number
  leaked_inr_total: number
  stolen_inr_total: number
  innocent_frozen_total: number
  innocent_frozen_mean: number
  innocent_frozen_rate: number
  frozen_accounts_mean: number
  precision: number
  time_to_first_freeze_median: number
  solve_ms_p50: number
  solve_ms_p95: number
  recovery_rate_p10: number
  recovery_rate_p90: number
  histogram: number[]
}

export interface DelayPoint {
  delay_minutes: number
  named_account_only: number
  chakravyuh_greedy: number
}

export interface InnocencePoint {
  innocence_budget: number
  recovery_rate: number
  innocent_frozen_mean: number
  frozen_accounts_mean: number
}

export interface OptimalityGap {
  n_incidents: number
  mean_gap?: number
  median_gap?: number
  max_gap?: number
  theoretical_bound?: number
  cpsat_ms_median?: number
  note?: string
  rows?: {
    incident_id: string
    accounts: number
    greedy_inr: number
    optimal_inr: number
    gap: number
    cpsat_ms: number
    status: string
  }[]
}

export interface Benchmark {
  generated_seconds: number
  n_incidents: number
  holdout_rings: string[]
  budget_k: number
  innocence_budget: number
  policy_labels: Record<string, string>
  policies: PolicySummary[]
  policies_adaptive_adversary: PolicySummary[]
  adversary_reroute_prob: number
  recovery_vs_delay: DelayPoint[]
  innocence_sweep: InnocencePoint[]
  optimality_gap: OptimalityGap
}

export interface DetectorTier {
  tier: string
  auc_pr: number
  precision_at_100: number
  precision_at_50: number
  precision: number
  recall: number
  flagged: number
  positives: number
  rows: number
}

export interface DetectorReport {
  holdout_rings: string[]
  n_train_incidents: number
  n_holdout_incidents: number
  tiers: DetectorTier[]
  rings: {
    incident: string
    accounts_clustered: number
    communities_found: number
    largest_community: number
    ari: number
    n_accounts: number
    n_communities: number
    n_true_rings: number
    mule_coverage: number
  }
  hard_negatives: {
    counts: Record<string, number>
    velocity: Record<string, Record<string, number>>
    shared_infrastructure: Record<string, Record<string, number>>
    velocity_separation: number
    shared_infrastructure_separation: number
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly path: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function get<T>(path: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(path)
  } catch {
    // Distinguish "backend is not running" from "backend said no" -- the UI
    // shows different recovery instructions for each.
    throw new ApiError('Could not reach the backend.', 0, path)
  }

  if (!response.ok) {
    let detail = `Request failed with ${response.status}.`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      /* response had no JSON body; keep the status message */
    }
    throw new ApiError(detail, response.status, path)
  }
  return (await response.json()) as T
}

async function post<T>(path: string, body: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new ApiError('Could not reach the backend.', 0, path)
  }

  if (!response.ok) {
    let detail = `Request failed with ${response.status}.`
    try {
      const parsed = (await response.json()) as { detail?: string }
      if (parsed.detail) detail = parsed.detail
    } catch {
      /* no JSON body; keep the status message */
    }
    throw new ApiError(detail, response.status, path)
  }
  return (await response.json()) as T
}

export const api = {
  health: () => get<HealthResponse>('/api/health'),
  scenarios: () => get<Scenario[]>('/api/scenarios'),
  graph: (scenarioId: string) => get<IncidentGraph>(`/api/graph/${scenarioId}`),
  rings: () => get<Ring[]>('/api/rings'),
  ringsFor: (scenarioId: string) =>
    get<DiscoveredRing[]>(`/api/rings/${scenarioId}`),
  datasetSummary: () => get<DatasetSummary>('/api/dataset/summary'),
  interdict: (request: InterdictRequest) =>
    post<InterdictResponse>('/api/interdict', request),
  account: (accountId: string, scenarioId: string, budgetK: number, innocence: number) =>
    get<AccountDetail>(
      `/api/account/${accountId}?scenario_id=${scenarioId}` +
        `&budget_k=${budgetK}&innocence_budget=${innocence}`,
    ),
  benchmark: () => get<Benchmark>('/api/evaluate'),
  detector: () => get<DetectorReport>('/api/detector'),
}

/** Absolute ws:// URL for the replay stream, honouring the Vite dev proxy. */
export function replayUrl(
  scenarioId: string,
  params: { policy: PolicyId; budgetK: number; innocenceBudget: number; fps: number },
): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const query = new URLSearchParams({
    policy: params.policy,
    budget_k: String(params.budgetK),
    innocence_budget: String(params.innocenceBudget),
    fps: String(params.fps),
  })
  return `${protocol}//${window.location.host}/ws/replay/${scenarioId}?${query}`
}
