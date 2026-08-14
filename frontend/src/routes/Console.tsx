import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { api, type GraphNode } from '@/api/client'
import FlowCanvas from '@/components/graph/FlowCanvas'
import ScenarioPicker from '@/components/console/ScenarioPicker'
import LedgerInset from '@/components/console/LedgerInset'
import Timeline from '@/components/console/Timeline'
import AccountDrawer from '@/components/inspect/AccountDrawer'
import { useReplay } from '@/hooks/useReplay'
import { count, duration, elapsed, rupees } from '@/lib/format'
import { tokens } from '@/theme/tokens'

const HORIZON_FALLBACK = 360

function Legend() {
  const items = [
    { color: tokens.textHi, label: 'victim' },
    { color: tokens.flow, label: 'mule account' },
    { color: tokens.burn, label: 'cash-out point' },
    { color: tokens.textLo, label: 'ordinary account' },
  ]
  return (
    <div className="flex items-center gap-4 bg-ink/85 backdrop-blur-sm px-3 py-1.5 rounded-panel border border-ink-line">
      {items.map((item) => (
        <span key={item.label} className="flex items-center gap-1.5 text-[11px] text-lo">
          <span
            className="inline-block w-2 h-2 rounded-full"
            style={{ backgroundColor: item.color }}
            aria-hidden
          />
          {item.label}
        </span>
      ))}
    </div>
  )
}

function DatasetMissing({ message }: { message: string }) {
  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="panel p-6 max-w-lg">
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle size={16} className="text-hi" aria-hidden />
          <h2 className="font-display text-base text-hi tracking-display">
            No dataset to load
          </h2>
        </div>
        <p className="text-[13px] text-lo mb-3 leading-relaxed">{message}</p>
        <pre className="font-mono text-[12px] text-hi bg-ink p-3 rounded-panel border border-ink-line">
          cd backend{'\n'}python -m app.simulator.generator
        </pre>
      </div>
    </div>
  )
}

export default function Console() {
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [scenarioId, setScenarioId] = useState<string | null>(null)

  const scenariosQuery = useQuery({ queryKey: ['scenarios'], queryFn: api.scenarios })

  useEffect(() => {
    if (!scenarioId && scenariosQuery.data?.length) {
      setScenarioId(scenariosQuery.data[0]!.scenario_id)
    }
  }, [scenariosQuery.data, scenarioId])

  const graphQuery = useQuery({
    queryKey: ['graph', scenarioId],
    queryFn: () => api.graph(scenarioId as string),
    enabled: Boolean(scenarioId),
  })

  const scenario = useMemo(
    () => scenariosQuery.data?.find((s) => s.scenario_id === scenarioId) ?? null,
    [scenariosQuery.data, scenarioId],
  )

  const replay = useReplay(
    graphQuery.data?.horizon_minutes ?? HORIZON_FALLBACK,
    scenarioId ?? '',
  )

  const reported = scenario ? replay.minute >= scenario.complaint_delay_minutes : false

  if (scenariosQuery.error) {
    return <DatasetMissing message={(scenariosQuery.error as Error).message} />
  }

  return (
    <div className="h-full flex">
      {/* ---------------------------------------------------------- left rail */}
      <aside className="w-[272px] shrink-0 border-r border-ink-line flex flex-col overflow-y-auto">
        <div className="px-4 pt-4 pb-3">
          <h2 className="label-lo mb-2">Incident</h2>
          {scenariosQuery.data ? (
            <ScenarioPicker
              scenarios={scenariosQuery.data}
              selectedId={scenarioId}
              onSelect={(id) => {
                setScenarioId(id)
                setSelectedNode(null)
              }}
            />
          ) : (
            <p className="text-[12px] text-lo">Loading incidents…</p>
          )}
        </div>

        {scenario && (
          <div className="px-4 py-4 border-t border-ink-line">
            <h2 className="label-lo mb-2">What happened</h2>
            <p className="text-[12px] text-lo leading-relaxed">{scenario.summary}</p>
          </div>
        )}

        {scenario && graphQuery.data && (
          <div className="px-4 py-4 border-t border-ink-line">
            <h2 className="label-lo mb-2">This incident</h2>
            <dl className="space-y-2 text-[12px]">
              {[
                ['Stolen', rupees(scenario.amount_inr)],
                ['Reported after', duration(scenario.complaint_delay_minutes)],
                ['Accounts in view', count(graphQuery.data.nodes.length)],
                ['Transfers', count(graphQuery.data.links.length)],
                ['Layers deep', String(scenario.hops)],
                ['Ring', scenario.ring_id],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-3">
                  <dt className="text-lo">{label}</dt>
                  <dd className="font-mono text-hi text-right">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        <div className="px-4 py-4 border-t border-ink-line mt-auto">
          <button
            type="button"
            disabled
            className="w-full py-2 rounded-panel border border-ink-line text-[12.5px] text-lo cursor-not-allowed"
            title="The freeze-frontier solver arrives in Phase 4"
          >
            Run interdiction
          </button>
          <p className="text-[11px] text-lo mt-2 leading-relaxed">
            Enabled once the freeze-frontier solver lands in Phase 4.
          </p>
        </div>
      </aside>

      {/* ------------------------------------------------------------- centre */}
      <section className="flex-1 min-w-0 flex flex-col relative">
        <div className="shrink-0 flex items-center justify-between px-5 h-11 border-b border-ink-line">
          <div className="flex items-baseline gap-3 min-w-0">
            {scenario ? (
              <>
                <span className="font-mono text-[12px] text-lo">
                  {scenario.scenario_id}
                </span>
                <span className="text-[13px] text-hi truncate">{scenario.name}</span>
              </>
            ) : (
              <span className="text-[13px] text-lo">Pick a scenario to begin</span>
            )}
          </div>

          {scenario && (
            <div className="flex items-center gap-3 shrink-0">
              <span
                className={[
                  'text-[11px] px-2 py-0.5 rounded-panel border',
                  reported
                    ? 'text-hi border-hi/40'
                    : 'text-lo border-ink-line',
                ].join(' ')}
              >
                {reported ? 'complaint filed' : 'nobody knows yet'}
              </span>
              <span className="font-mono text-[13px] text-hi tabular-nums">
                {elapsed(replay.minute)}
              </span>
            </div>
          )}
        </div>

        <div className="flex-1 min-h-0 relative">
          {graphQuery.isPending && scenarioId && (
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="flex items-center gap-2 text-[13px] text-lo">
                <Loader2 size={14} className="animate-spin" aria-hidden />
                Tracing where the money went…
              </span>
            </div>
          )}

          {graphQuery.error && (
            <div className="absolute inset-0 flex items-center justify-center p-6">
              <p className="text-[13px] text-lo max-w-md text-center">
                {(graphQuery.error as Error).message}
              </p>
            </div>
          )}

          {graphQuery.data && (
            <FlowCanvas
              graph={graphQuery.data}
              minute={replay.minute}
              selectedId={selectedNode?.id ?? null}
              onSelect={setSelectedNode}
            />
          )}

          <div className="absolute left-5 bottom-4 pointer-events-none">
            <Legend />
          </div>

          <AccountDrawer node={selectedNode} onClose={() => setSelectedNode(null)} />
        </div>

        {scenario && graphQuery.data && (
          <div className="shrink-0 border-t border-ink-line">
            <Timeline
              graph={graphQuery.data}
              replay={replay}
              complaintMinute={scenario.complaint_delay_minutes}
            />
          </div>
        )}

        <div className="shrink-0 p-4 border-t border-ink-line">
          {scenario && graphQuery.data ? (
            <LedgerInset
              scenario={scenario}
              graph={graphQuery.data}
              minute={replay.minute}
            />
          ) : (
            <div className="ledger px-6 py-8 text-center text-[13px] text-paper-text/60">
              Pick a scenario to see where its money went.
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
