import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { FileText, Loader2, Play, RotateCcw } from 'lucide-react'
import { api, type GraphNode } from '@/api/client'
import FlowCanvas from '@/components/graph/FlowCanvas'
import FreezeFrontier from '@/components/graph/FreezeFrontier'
import ScenarioPicker from '@/components/console/ScenarioPicker'
import BudgetControls from '@/components/console/BudgetControls'
import FreezeQueue from '@/components/console/FreezeQueue'
import IntakeForm from '@/components/console/IntakeForm'
import PolicyCompare from '@/components/console/PolicyCompare'
import PolicySwitcher from '@/components/console/PolicySwitcher'
import SplitCompare, {
  type AdversaryNote,
} from '@/components/console/SplitCompare'
import IncidentTimeline from '@/components/console/IncidentTimeline'
import LayoutToggle from '@/components/console/LayoutToggle'
import LedgerStrip from '@/components/console/LedgerStrip'
import Splitter from '@/components/console/Splitter'
import AccountDrawer from '@/components/inspect/AccountDrawer'
import CaseHeader from '@/components/portal/CaseHeader'
import { RouteError } from '@/components/layout/RouteState'
import { useReplayStream } from '@/hooks/useReplayStream'
import { useAudit } from '@/store/audit'
import { runKey, useConsole } from '@/store/console'
import { count } from '@/lib/format'
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

export default function Console() {
  const navigate = useNavigate()
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
  const passiveRecovery = useConsole((s) => s.passiveRecovery)
  const rememberPassiveRecovery = useConsole((s) => s.rememberPassiveRecovery)
  const rememberPolicyRun = useConsole((s) => s.rememberPolicyRun)
  const record = useAudit((s) => s.record)
  const filedIncidents = useConsole((s) => s.filedIncidents)

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

  // Seeded scenarios plus anything filed through intake this session. Merging
  // here rather than special-casing means the picker, the docket, the timeline
  // and the ledger all treat a filed complaint as an ordinary case.
  const cases = useMemo(
    () => [...(scenariosQuery.data ?? []), ...filedIncidents],
    [scenariosQuery.data, filedIncidents],
  )

  const scenario = useMemo(
    () => cases.find((s) => s.scenario_id === scenarioId) ?? null,
    [cases, scenarioId],
  )

  const stream = useReplayStream(
    scenarioId,
    policy,
    budgetK,
    innocenceBudget,
    adaptive,
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
    onSuccess: (data) => {
      const share = data.amount_inr > 0 ? data.outcome.prevented_inr / data.amount_inr : 0
      // Passive runs are the reference the adaptive caption reads back later.
      if (!adaptive && scenarioId && data.amount_inr > 0) {
        rememberPassiveRecovery(
          runKey(scenarioId, policy, budgetK, innocenceBudget),
          share,
        )
      }
      // Every run feeds the head-to-head strip, so switching policy during the
      // demo accumulates a comparison rather than replacing one.
      if (scenarioId) {
        rememberPolicyRun(scenarioId, {
          policy: data.policy,
          policyLabel: data.policy_label,
          recoveryShare: share,
          preventedInr: data.outcome.prevented_inr,
          innocentFrozen: data.outcome.innocent_frozen,
          frozen: data.plan.length,
          budgetK: data.budget_k,
          innocenceBudget: data.innocence_budget,
          adaptiveAdversary: data.adaptive_adversary,
        })
      }
      record('solve', `Plan produced for ${data.scenario_id}`, {
        policy: data.policy,
        budget_k: data.budget_k,
        innocence_budget: data.innocence_budget,
        adaptive_adversary: data.adaptive_adversary,
        instructions: data.plan.length,
        solve_ms: Math.round(data.solve_ms),
        candidates_scored: data.candidates_considered,
        prevented_inr: Math.round(data.outcome.prevented_inr),
        innocent_frozen: data.outcome.innocent_frozen,
      })
      setPhase('running')
      stream.start()
    },
    onError: (error) => {
      record('solve', 'Solve failed', { error: (error as Error).message })
      setPhase('idle')
    },
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

  // One line per case opened, so the log starts where the operator did.
  useEffect(() => {
    if (scenario) {
      record('case', `Case opened: ${scenario.case_id}`, {
        scenario: scenario.scenario_id,
        complaint_ref: scenario.complaint_ref,
        amount_inr: scenario.amount_inr,
        reported_after_min: scenario.complaint_delay_minutes,
      })
    }
  }, [scenario?.scenario_id])  // eslint-disable-line react-hooks/exhaustive-deps

  const plan = interdiction.data?.plan ?? []
  const busy = phase === 'planning' || interdiction.isPending

  // Only annotate an adaptive run, and only once the figures on screen came
  // from that run -- the caption must never describe a result it is not
  // sitting next to.
  const adversaryNote = useMemo((): AdversaryNote | null => {
    const result = interdiction.data
    if (!result || !result.adaptive_adversary || result.amount_inr <= 0) {
      return null
    }
    return {
      reroutedTransfers: result.outcome.rerouted_transfers,
      recoveryShare: result.outcome.prevented_inr / result.amount_inr,
      passiveRecoveryShare:
        passiveRecovery[
          runKey(
            result.scenario_id,
            result.policy,
            result.budget_k,
            result.innocence_budget,
          )
        ] ?? null,
    }
  }, [interdiction.data, passiveRecovery])

  if (scenariosQuery.error) {
    return <RouteError error={scenariosQuery.error} subject="the case list" />
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
        {/* Collapsed to a dropdown: the ordered freeze plan below is the
            product, and six scenario cards were pushing it under the fold on a
            1366x768 projector. Choosing the case is a five-second act at the
            start; reading the plan is the rest of the demo. */}
        <div className="px-4 pt-2.5 pb-2 shrink-0">
          {cases.length > 0 ? (
            <ScenarioPicker
              scenarios={cases}
              selectedId={scenarioId}
              onSelect={setScenario}
            />
          ) : (
            <p className="text-[14px] text-lo">Loading cases…</p>
          )}
          <div className="mt-2">
            <IntakeForm scenarios={scenariosQuery.data} />
          </div>
        </div>

        <div className="px-4 py-2 border-t border-ink-line shrink-0">
          <h2 className="label-lo mb-1">Who plans it</h2>
          <PolicySwitcher />
        </div>

        <div className="px-4 py-2 border-t border-ink-line shrink-0">
          <BudgetControls plan={plan} />
        </div>

        <div className="px-4 py-2 border-t border-ink-line shrink-0">
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

          {/* The closing beat: complaint -> plan -> replay -> signed order.
              Only offered once the replay has finished, because issuing
              instructions from a half-watched plan is not the story. */}
          {phase === 'done' && plan.length > 0 && (
            <button
              type="button"
              onClick={() => navigate('/orders')}
              className="w-full mt-2 py-2 rounded-panel border border-ink-line text-[15.5px] text-lo hover:text-hi hover:border-hi/40 flex items-center justify-center gap-2 transition-colors"
            >
              <FileText size={13} aria-hidden />
              Generate freeze orders
            </button>
          )}

          {interdiction.error && (
            <p className="text-[13px] text-lo mt-2 leading-relaxed">
              {(interdiction.error as Error).message}
            </p>
          )}

          {/* One dense line rather than a four-row table. The numbers still
              matter -- they answer "does it run fast enough" -- but they are
              reference, not the headline, and they were costing the freeze
              queue sixty pixels it needed more. */}
          {interdiction.data && (
            <p
              className="mt-2 text-[12px] text-lo leading-snug"
              title="Solve time · accounts the solver scored · nodes drawn · rollouts × particles"
            >
              <span className="font-mono text-hi tabular-nums">
                {interdiction.data.solve_ms.toFixed(0)} ms
              </span>{' '}
              ·{' '}
              <span className="font-mono text-hi tabular-nums">
                {count(interdiction.data.candidates_considered)}
              </span>{' '}
              checked ·{' '}
              <span className="font-mono text-hi tabular-nums">
                {count(graphQuery.data?.nodes.length ?? 0)}
              </span>{' '}
              drawn ·{' '}
              <span className="font-mono text-hi tabular-nums">
                {count(interdiction.data.rollouts)}×
                {count(
                  Math.round(
                    interdiction.data.particles / interdiction.data.rollouts,
                  ),
                )}
              </span>{' '}
              sims
            </p>
          )}
        </div>

        {/* Floor rather than min-h-0: the queue keeps a usable height and the
            rail scrolls instead, which beats collapsing it to nothing. */}
        <div className="px-4 py-2 border-t border-ink-line flex-1 min-h-[150px] flex flex-col">
          <div className="flex items-baseline justify-between mb-1.5 shrink-0">
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
        {/* The case docket. Replaces the old scenario strip: same job, but it
            quotes the case and complaint references the freeze order and the
            audit trail use, and it counts down the recoverable window. */}
        <CaseHeader
          scenario={scenario}
          phase={phase}
          minute={minute}
          actions={scenario ? <LayoutToggle /> : null}
        />

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
              idle={phase === 'idle'}
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

        {/* The live head-to-head, directly under the canvas it describes. */}
        <div className="shrink-0">
          <PolicyCompare scenarioId={scenarioId} activePolicy={policy} />
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
            {/* The cap is what keeps the graph on screen. The drag height is a
                preference; on a 1366x768 projector, with the portal chrome
                above, an unclamped 330px band left the canvas about forty
                pixels tall. The canvas keeps the majority of the space no
                matter what the divider was last dragged to. */}
            <div
              className="shrink-0 overflow-y-auto p-4"
              style={
                layout === 'side'
                  ? { width: ledgerWidth, maxWidth: '42%' }
                  : { height: ledgerHeight, maxHeight: '46%' }
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
                adversary={adversaryNote}
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
