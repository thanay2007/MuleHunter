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
}

export interface GraphLink {
  source: string
  target: string
  amount: number
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

export const api = {
  health: () => get<HealthResponse>('/api/health'),
  scenarios: () => get<Scenario[]>('/api/scenarios'),
  graph: (scenarioId: string) => get<IncidentGraph>(`/api/graph/${scenarioId}`),
  rings: () => get<Ring[]>('/api/rings'),
  datasetSummary: () => get<DatasetSummary>('/api/dataset/summary'),
}
