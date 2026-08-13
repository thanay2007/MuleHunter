/**
 * Typed API client. Every backend response gets an explicit interface here --
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
    throw new ApiError(`Request failed with ${response.status}.`, response.status, path)
  }
  return (await response.json()) as T
}

export const api = {
  health: () => get<HealthResponse>('/api/health'),
}