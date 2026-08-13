import { useQuery } from '@tanstack/react-query'
import { Activity, AlertTriangle, Check, Minus } from 'lucide-react'
import { ApiError, api, type ArtifactStatus, type HealthResponse } from './api/client'

/**
 * Phase 0 shell. Its only job is to prove the frontend reads live backend
 * state. The Operations Console replaces this in Phase 5.
 */

const PHASE_NAMES: readonly string[] = [
  'scaffold',
  'simulator',
  'graph store',
  'detection',
  'interdiction solver',
  'operations console',
  'evaluation harness',
  'explainability & polish',
]

const ARTIFACT_LABELS: ReadonlyArray<[keyof ArtifactStatus, string]> = [
  ['accounts', 'accounts.parquet'],
  ['transactions', 'transactions.parquet'],
  ['labels', 'labels.parquet'],
  ['warehouse', 'chakravyuh.duckdb'],
  ['benchmark', 'benchmark.json'],
]

function ArtifactRow({ label, present }: { label: string; present: boolean }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-ink-line last:border-0">
      <span className="font-mono text-[13px] text-hi">{label}</span>
      {present ? (
        <span className="flex items-center gap-1.5 text-[11px] text-hi">
          <Check size={13} strokeWidth={2} aria-hidden />
          present
        </span>
      ) : (
        <span className="flex items-center gap-1.5 text-[11px] text-lo">
          <Minus size={13} strokeWidth={2} aria-hidden />
          not generated
        </span>
      )}
    </div>
  )
}

function HealthPanel({ health }: { health: HealthResponse }) {
  const phaseName = PHASE_NAMES[health.phase] ?? 'unknown'

  return (
    <div className="panel p-6 w-full max-w-2xl">
      <div className="flex items-baseline justify-between mb-5">
        <h2 className="font-display text-lg tracking-display text-hi">Backend connected</h2>
        <span className="font-mono text-[12px] text-lo">
          v{health.version} · up {health.uptime_seconds.toFixed(1)}s
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-x-8 gap-y-3 mb-6">
        <div>
          <dt className="label-lo">Phase</dt>
          <dd className="font-mono text-[13px] text-hi">
            {health.phase} — {phaseName}
          </dd>
        </div>
        <div>
          <dt className="label-lo">Master seed</dt>
          <dd className="font-mono text-[13px] text-hi">{health.master_seed}</dd>
        </div>
      </dl>

      <h3 className="label-lo mb-1">Generated artifacts</h3>
      <div>
        {ARTIFACT_LABELS.map(([key, label]) => (
          <ArtifactRow key={key} label={label} present={health.artifacts[key]} />
        ))}
      </div>
    </div>
  )
}

function ErrorPanel({ error }: { error: unknown }) {
  const unreachable = error instanceof ApiError && error.status === 0
  return (
    <div className="panel p-6 w-full max-w-2xl">
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle size={16} strokeWidth={2} className="text-hi" aria-hidden />
        <h2 className="font-display text-lg tracking-display text-hi">
          {unreachable ? 'Backend is not running' : 'Backend returned an error'}
        </h2>
      </div>
      <p className="text-[13px] text-lo mb-3 leading-relaxed">
        {unreachable
          ? 'Nothing is listening on port 8000. The page has no data to show until the API is up.'
          : error instanceof Error
            ? error.message
            : 'An unknown error occurred.'}
      </p>
      <p className="label-lo mb-1">Try this</p>
      <pre className="font-mono text-[12px] text-hi bg-ink p-3 rounded-panel border border-ink-line overflow-x-auto">
        cd backend{'\n'}uvicorn app.main:app --reload --port 8000
      </pre>
    </div>
  )
}

export default function App() {
  const { data, error, isPending } = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 5_000,
  })

  return (
    <div className="min-h-full flex flex-col">
      <header className="flex items-center justify-between px-6 h-14 border-b border-ink-line">
        <div className="flex items-baseline gap-3">
          <span className="font-display text-base tracking-display text-hi">chakravyuh</span>
          <span className="text-[12px] text-lo">fraud interdiction console</span>
        </div>
        <span className="flex items-center gap-1.5 font-mono text-[12px] text-lo">
          <Activity size={13} strokeWidth={2} aria-hidden />
          {isPending ? 'connecting' : error ? 'offline' : 'live'}
        </span>
      </header>

      <main className="flex-1 flex items-center justify-center p-8">
        {isPending ? (
          <p className="text-[13px] text-lo">Connecting to the backend…</p>
        ) : error ? (
          <ErrorPanel error={error} />
        ) : (
          <HealthPanel health={data} />
        )}
      </main>
    </div>
  )
}