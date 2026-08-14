import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, Loader2, Play, RotateCcw } from 'lucide-react'
import { api, type GraphNode } from '@/api/client'
import FlowCanvas from '@/components/graph/FlowCanvas'
import FreezeFrontier from '@/components/graph/FreezeFrontier'
import ScenarioPicker from '@/components/console/ScenarioPicker'
import BudgetControls from '@/components/console/BudgetControls'
import FreezeQueue from '@/components/console/FreezeQueue'
import SplitCompare from '@/components/console/SplitCompare'
import IncidentTimeline from '@/components/console/IncidentTimeline'
import LayoutToggle from '@/components/console/LayoutToggle'
import LedgerStrip from '@/components/console/LedgerStrip'
import Splitter from '@/components/console/Splitter'
import AccountDrawer from '@/components/inspect/AccountDrawer'
import { useReplayStream } from '@/hooks/useReplayStream'
import { useConsole } from '@/store/console'
import { count, duration, rupees } from '@/lib/format'
import { tokens } from '@/theme/tokens'

const REPLAY_FPS = 12
/** Used for the timeline before the stream header arrives with the real value. */
const REPLAY_HORIZON_FALLBACK = 360

function Legend() {
  const items = [
    { color: tokens.textHi, label: 'victim' },
    { color: tokens.flow, label: 'stolen money' },
    { color: tokens.interdict, label: 'frozen' },
    { color: tokens.burn, label: 'money leaves' },
    { color: tokens.textLo, label: 'normal account' },
  ]
  return (
    <div className="flex items-center gap-4 bg-ink/85 backdrop-blur-sm px-3 py-1.5 rounded-panel border border-ink-line">
      {items.map((item) => (
        <span
          key={item.label}
          className="flex items-center gap-1.5 text-[13px] text-lo"
        >
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
            No data loaded
          </h2>
        </div>
        <p className="text-[15.5px] text-lo mb-3 leading-relaxed">{message}</p>
        <pre className="font-mono text-[14px] text-hi bg-ink p-3 rounded-panel border border-ink-line whitespace-pre-wrap">
          cd backend{'\n'}
          python -m app.simulator.generator{'\n'}
          python -m app.detect.train
        </pre>
      </div>
    </div>
  )
}

export default function Console() {
  const scenarioId = useConsole((s) => s.scenarioId)
  const policy = useConsole((s) => s.policy)
  const budgetK = useConsole((s) => s.budgetK)
  const innocenceBudget = useConsole((s) => s.innocenceBudget)
  const adaptive = useConsole((s) => s.adaptiveAdversary)
  const selectedNode = useConsole((s) => s.selectedNode)
  const phase = useConsole((s) => s.phase)
  const layout = useConsole((s) => s.layout)
  const ledgerHeight = useConsole((s) => s.ledgerHeight)
  const ledgerWidth = useConsole((s) => s.ledgerWidth)
  const setScenario = useConsole((s) => s.setScenario)
  const selectNode = useConsole((s) => s.selectNode)
  const setPhase = useConsole((s) => s.setPhase)
  const setLayout = useConsole((s) => s.setLayout)
  const setLedgerHeight = useConsole((s) => s.setLedgerHeight)
  const setLedgerWidth = useConsole((s) => s.setLedgerWidth)

  const [sweepTrigger, setSweepTrigger] = useState(0)
  const sweptFor = useRef<string | null>(null)

  const scenariosQuery = useQuery({
    queryKey: ['scenarios'],
    queryFn: api.scenarios,
  })

  useEffect(() => {
    if (!scenarioId && scenariosQuery.data?.length) {
      setScenario(scenariosQuery.data[0]!.scenario_id)
    }
  }, [scenariosQuery.data, scenarioId, setScenario])

  const graphQuery = useQuery({
    queryKey: ['graph', scenarioId],
    queryFn: () => api.graph(scenarioId as string),
    enabled: Boolean(scenarioId),
  })

  const scenario = useMemo(
    () => scenariosQuery.data?.find((s) => s.scenario_id === scenarioId) ?? null,
    [scenariosQuery.data, scenarioId],
  )

  const stream = useReplayStream(
    scenarioId,
    policy,
    budgetK,
    innocenceBudget,
    REPLAY_FPS,
  )

  const interdiction = useMutation({
    mutationFn: () =>
      api.interdict({
        scenario_id: scenarioId as string,
        policy,
        budget_k: budgetK,
        innocence_budget: innocenceBudget,
        adaptive_adversary: adaptive,
      }),
    onSuccess: () => {
      setPhase('running')
      stream.start()
    },
    onError: () => setPhase('idle'),
  })

  const run = useCallback(() => {
    if (!scenarioId) return
    sweptFor.current = null
    setPhase('planning')
    interdiction.mutate()
  }, [scenarioId, setPhase, interdiction])

  // The frontier sweep fires once, at the minute the first instruction lands.
  const minute = stream.frame?.minute ?? 0
  const firstIssue = interdiction.data?.plan[0]?.issue_at_minute ?? null
  useEffect(() => {
    if (firstIssue === null || !scenarioId) return
    if (sweptFor.current === scenarioId) return
    if (minute >= firstIssue) {
      sweptFor.current = scenarioId
      setSweepTrigger((n) => n + 1)
    }
  }, [minute, firstIssue, scenarioId])

  useEffect(() => {
    if (stream.status === 'done') setPhase('done')
  }, [stream.status, setPhase])

  const reported = scenario ? minute >= scenario.complaint_delay_minutes : false
  const plan = interdiction.data?.plan ?? []
  const busy = phase === 'planning' || interdiction.isPending

  if (scenariosQuery.error) {
    return <DatasetMissing message={(scenariosQuery.error as Error).message} />
  }

  return (
    <div className="h-full flex">
      {/* ---------------------------------------------------------- left rail */}
      {/* The freeze queue scrolls inside its own box so it does not slide below
          the fold as instructions accumulate. The rail can still scroll as a
          whole when the viewport is too short for the fixed sections above it
          -- without that fallback the solver stats were being clipped off the
          bottom edge rather than becoming reachable. */}
      <aside className="w-[286px] shrink-0 border-r border-ink-line flex flex-col overflow-y-auto">
        <div className="px-4 pt-4 pb-3 shrink-0 max-h-[38%] overflow-y-auto">
          <h2 className="label-lo mb-2">Pick a case</h2>
          {scenariosQuery.data ? (
            <ScenarioPicker
              scenarios={scenariosQuery.data}
              selectedId={scenarioId}
              onSelect={setScenario}
            />
          ) : (
            <p className="text-[14px] text-lo">Loading cases…</p>
          )}
        </div>

        <div className="px-4 py-4 border-t border-ink-line shrink-0">
          <h2 className="label-lo mb-3">Limits</h2>
          <BudgetControls />
        </div>

        <div className="px-4 py-4 border-t border-ink-line shrink-0">
          <button
            type="button"
            onClick={run}
            disabled={!scenarioId || busy}
            className={[
              'w-full py-2 rounded-panel border text-[15.5px] flex items-center justify-center gap-2 transition-colors',
              busy
                ? 'border-ink-line text-lo cursor-wait'
                : 'border-hi/40 text-hi hover:bg-ink-raised',
            ].join(' ')}
          >
            {busy ? (
              <>
                <Loader2 size={13} className="animate-spin" aria-hidden />
                Solving…
              </>
            ) : phase === 'done' || phase === 'running' ? (
              <>
                <RotateCcw size={13} aria-hidden />
                Run again
              </>
            ) : (
              <>
                <Play size={13} aria-hidden />
                Run interdiction
              </>
            )}
          </button>

          {interdiction.error && (
            <p className="text-[13px] text-lo mt-2 leading-relaxed">
              {(interdiction.error as Error).message}
            </p>
          )}

          {interdiction.data && (
            <dl className="mt-3 space-y-1.5">
              {[
                ['Time to solve', `${interdiction.data.solve_ms.toFixed(0)} ms`],
                // Two different sets, deliberately named apart: the solver
                // scores every account the money could reach, while the canvas
                // draws only the ones it actually did.
                ['Accounts checked', count(interdiction.data.candidates_considered)],
                [
                  'Shown here',
                  count(graphQuery.data?.nodes.length ?? 0),
                ],
                [
                  'Simulations',
                  `${count(interdiction.data.rollouts)} × ${count(
                    Math.round(
                      interdiction.data.particles / interdiction.data.rollouts,
                    ),
                  )}`,
                ],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-2 text-[13px]">
                  <dt className="text-lo">{label}</dt>
                  <dd className="font-mono text-hi tabular-nums">{value}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>

        {/* Floor rather than min-h-0: the queue keeps a usable height and the
            rail scrolls instead, which beats collapsing it to nothing. */}
        <div className="px-4 py-4 border-t border-ink-line flex-1 min-h-[190px] flex flex-col">
          <div className="flex items-baseline justify-between mb-2 shrink-0">
            <h2 className="label-lo">Accounts to freeze</h2>
            {plan.length > 0 && (
              <span className="font-mono text-[13px] text-lo tabular-nums">
                {count(plan.filter((s) => s.issue_at_minute <= minute).length)} /{' '}
                {count(plan.length)}
              </span>
            )}
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto -mr-1 pr-1">
          <FreezeQueue
            plan={plan}
            minute={minute}
            selectedId={selectedNode?.id ?? null}
            onSelect={(accountId) =>
              selectNode(
                graphQuery.data?.nodes.find((n) => n.id === accountId) ??
                  ({ id: accountId } as GraphNode),
              )
            }
          />
          </div>
        </div>
      </aside>

      {/* ------------------------------------------------------------- centre */}
      <section className="flex-1 min-w-0 flex flex-col relative">
        <div className="shrink-0 flex items-center justify-between px-5 h-11 border-b border-ink-line">
          <div className="flex items-baseline gap-3 min-w-0">
            {scenario ? (
              <>
                <span className="font-mono text-[14px] text-lo">
                  {scenario.scenario_id}
                </span>
                <span className="text-[15.5px] text-hi truncate">
                  {scenario.name}
                </span>
              </>
            ) : (
              <span className="text-[15.5px] text-lo">Pick a case to begin</span>
            )}
          </div>

          {/* The clock and replay state live on the timeline below; repeating
              them here just crowds the bar. */}
          {scenario && (
            <div className="flex items-center gap-3 shrink-0">
              <span className="text-[13px] text-lo">
                <span className="font-mono tabular-nums text-hi">
                  {rupees(scenario.amount_inr)}
                </span>{' '}
                · reported after {duration(scenario.complaint_delay_minutes)}
              </span>
              <span
                className={[
                  'text-[13px] px-2 py-0.5 rounded-panel border',
                  reported ? 'text-hi border-hi/40' : 'text-lo border-ink-line',
                ].join(' ')}
              >
                {reported ? 'reported' : 'not reported yet'}
              </span>
              <LayoutToggle />
            </div>
          )}
        </div>

      {/* Canvas and ledger share the remaining space. In `side` they sit next
          to each other; otherwise the ledger sits underneath. The timeline
          always stays directly under the graph, because it is the transport for
          the thing you are watching. */}
      <div
        className={[
          'flex-1 min-h-0',
          layout === 'side' ? 'flex' : 'flex flex-col',
        ].join(' ')}
      >
        <div className="flex-1 min-w-0 min-h-0 flex flex-col">
        <div className="flex-1 min-h-0 relative">
          {graphQuery.isPending && scenarioId && (
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="flex items-center gap-2 text-[15.5px] text-lo">
                <Loader2 size={14} className="animate-spin" aria-hidden />
                Following the money…
              </span>
            </div>
          )}

          {graphQuery.error && (
            <div className="absolute inset-0 flex items-center justify-center p-6">
              <p className="text-[15.5px] text-lo max-w-md text-center">
                {(graphQuery.error as Error).message}
              </p>
            </div>
          )}

          {graphQuery.data && (
            <FlowCanvas
              graph={graphQuery.data}
              minute={minute}
              selectedId={selectedNode?.id ?? null}
              frozen={stream.frozen}
              justFrozen={stream.justFrozen}
              onSelect={selectNode}
            />
          )}

          <FreezeFrontier trigger={sweepTrigger} active={phase !== 'idle'} />

          {phase === 'idle' && graphQuery.data && (
            <div className="absolute inset-x-0 bottom-16 flex justify-center pointer-events-none">
              <p className="text-[14px] text-lo bg-ink/85 backdrop-blur-sm px-3 py-1.5 rounded-panel border border-ink-line">
                Press <span className="text-hi">Run interdiction</span> to watch the money
                move and the freezes land.
              </p>
            </div>
          )}

          <div className="absolute left-5 bottom-4 pointer-events-none">
            <Legend />
          </div>

          <AccountDrawer
            accountId={selectedNode?.id ?? null}
            scenarioId={scenarioId}
            budgetK={budgetK}
            innocenceBudget={innocenceBudget}
            onClose={() => selectNode(null)}
          />
        </div>

        {scenario && (
          <div className="shrink-0 border-t border-ink-line">
            <IncidentTimeline
              header={stream.header}
              fallbackHorizon={REPLAY_HORIZON_FALLBACK}
              complaintMinute={scenario.complaint_delay_minutes}
              minute={minute}
              plan={plan}
              status={stream.status}
            />
          </div>
        )}

        </div>

        {/* --------------------------------------------------------- ledger */}
        {layout === 'focus' ? (
          <div className="shrink-0 p-3 border-t border-ink-line">
            <LedgerStrip
              frame={stream.frame}
              amountInr={scenario?.amount_inr ?? 0}
              onExpand={() => setLayout('stacked')}
            />
          </div>
        ) : (
          <>
            <Splitter
              orientation={layout === 'side' ? 'vertical' : 'horizontal'}
              size={layout === 'side' ? ledgerWidth : ledgerHeight}
              onChange={layout === 'side' ? setLedgerWidth : setLedgerHeight}
              min={layout === 'side' ? 320 : 120}
              max={layout === 'side' ? 760 : Math.max(240, window.innerHeight - 300)}
              label={
                layout === 'side' ? 'Resize the money panel' : 'Resize the money panel'
              }
            />
            <div
              className={[
                'shrink-0 overflow-y-auto',
                layout === 'side' ? 'p-4' : 'p-4',
              ].join(' ')}
              style={
                layout === 'side'
                  ? { width: ledgerWidth }
                  : { height: ledgerHeight }
              }
            >
            {scenario ? (
              <SplitCompare
                frame={stream.frame}
                header={stream.header}
                amountInr={scenario.amount_inr}
                innocentFrozen={
                  interdiction.data?.outcome.innocent_frozen ??
                  stream.header?.final.chakravyuh.innocent_frozen ??
                  0
                }
                baselineInnocentFrozen={
                  stream.header?.final.baseline.innocent_frozen ?? 0
                }
                dense={layout === 'side'}
              />
            ) : (
              <div className="ledger px-6 py-8 text-center text-[15.5px] text-paper-text/60">
                Pick a case to see where its money went.
              </div>
            )}
            </div>
          </>
        )}
      </div>
      </section>
    </div>
  )
}
