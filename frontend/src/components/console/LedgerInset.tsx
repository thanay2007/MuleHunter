import { useMemo } from 'react'
import { Lock } from 'lucide-react'
import type { IncidentGraph, Scenario } from '@/api/client'
import { count, duration, rupees } from '@/lib/format'
import Counter from './Counter'

/**
 * The ledger inset -- warm passbook paper against the dark chrome.
 *
 * Only money goes on paper. Every figure here is measured from the recorded
 * incident in the dataset; nothing is projected or modelled. The interdiction
 * comparison that eventually sits on the right needs the Phase 4 solver, and
 * until that exists this panel says so rather than showing a number we cannot
 * defend.
 */

interface Props {
  scenario: Scenario
  graph: IncidentGraph
}

interface Exposure {
  reachedExit: number
  minutesToFirstExit: number | null
  minutesToLastExit: number | null
  exitsUsed: number
  mulesTouched: number
  banksTouched: number
}

function computeExposure(graph: IncidentGraph): Exposure {
  const exitIds = new Set(graph.nodes.filter((n) => n.kind === 'exit').map((n) => n.id))
  const banks = new Set<string>()
  let reachedExit = 0
  let first: number | null = null
  let last: number | null = null
  const usedExits = new Set<string>()

  for (const node of graph.nodes) {
    if (node.kind === 'mule') banks.add(node.bank_id)
  }

  for (const link of graph.links) {
    if (!link.is_fraud) continue
    const target = typeof link.target === 'string' ? link.target : ''
    if (!exitIds.has(target)) continue

    reachedExit += link.amount
    usedExits.add(target)
    first = first === null ? link.minute : Math.min(first, link.minute)
    last = last === null ? link.minute : Math.max(last, link.minute)
  }

  return {
    reachedExit,
    minutesToFirstExit: first,
    minutesToLastExit: last,
    exitsUsed: usedExits.size,
    mulesTouched: graph.nodes.filter((n) => n.kind === 'mule').length,
    banksTouched: banks.size,
  }
}

function Figure({
  label,
  children,
  tone,
}: {
  label: string
  children: React.ReactNode
  tone?: 'lost' | 'plain'
}) {
  return (
    <div>
      <div
        className={`text-[22px] leading-none ${
          tone === 'lost' ? 'text-burn' : 'text-paper-text'
        }`}
      >
        {children}
      </div>
      <div className="text-[11px] text-paper-text/60 mt-1.5">{label}</div>
    </div>
  )
}

export default function LedgerInset({ scenario, graph }: Props) {
  const exposure = useMemo(() => computeExposure(graph), [graph])

  const escapedBeforeComplaint = useMemo(() => {
    const exitIds = new Set(graph.nodes.filter((n) => n.kind === 'exit').map((n) => n.id))
    let sum = 0
    for (const link of graph.links) {
      if (!link.is_fraud) continue
      const target = typeof link.target === 'string' ? link.target : ''
      if (!exitIds.has(target)) continue
      if (link.minute <= scenario.complaint_delay_minutes) sum += link.amount
    }
    return sum
  }, [graph, scenario.complaint_delay_minutes])

  return (
    <div className="ledger px-6 py-5">
      <div className="flex items-baseline justify-between mb-4">
        <h2 className="font-display text-[15px] text-paper-text tracking-display">
          Incident ledger
        </h2>
        <span className="font-mono text-[11px] text-paper-text/55">
          measured from recorded transactions
        </span>
      </div>

      <div className="grid grid-cols-4 gap-6">
        <Figure label="Amount stolen">
          <Counter value={scenario.amount_inr} format={rupees} />
        </Figure>

        <Figure label="Reached cash-out" tone="lost">
          <Counter value={exposure.reachedExit} format={rupees} />
        </Figure>

        <Figure label="Gone before the victim even reported">
          <span className="text-burn">
            <Counter value={escapedBeforeComplaint} format={rupees} />
          </span>
        </Figure>

        <Figure label="Mule accounts money passed through">
          <span className="font-mono">{count(exposure.mulesTouched)}</span>
        </Figure>
      </div>

      <div className="mt-5 pt-4 border-t border-paper-line grid grid-cols-4 gap-6 text-[12px] text-paper-text/75">
        <div>
          <span className="font-mono text-paper-text">
            {exposure.minutesToFirstExit === null
              ? '—'
              : duration(exposure.minutesToFirstExit)}
          </span>
          <div className="text-[11px] text-paper-text/55 mt-0.5">
            until the first rupee left the banking system
          </div>
        </div>
        <div>
          <span className="font-mono text-paper-text">
            {duration(scenario.complaint_delay_minutes)}
          </span>
          <div className="text-[11px] text-paper-text/55 mt-0.5">
            until the victim reported it
          </div>
        </div>
        <div>
          <span className="font-mono text-paper-text">{exposure.banksTouched}</span>
          <div className="text-[11px] text-paper-text/55 mt-0.5">
            banks the money crossed
          </div>
        </div>
        <div>
          <span className="font-mono text-paper-text">{exposure.exitsUsed}</span>
          <div className="text-[11px] text-paper-text/55 mt-0.5">
            cash-out points used
          </div>
        </div>
      </div>

      <div className="mt-5 pt-4 border-t border-paper-line flex items-start gap-2.5">
        <Lock size={14} strokeWidth={2} className="text-paper-text/45 mt-0.5" aria-hidden />
        <p className="text-[12px] text-paper-text/70 leading-relaxed">
          <span className="text-paper-text">Interdiction comparison lands in Phase 4.</span>{' '}
          This panel will split into current bank practice against Chakravyuh, with
          recovered rupees and innocent accounts frozen under each. Those figures need the
          freeze-frontier solver, so nothing is shown for them yet.
        </p>
      </div>
    </div>
  )
}
