import { useMemo } from 'react'
import { Lock } from 'lucide-react'
import type { IncidentGraph, Scenario } from '@/api/client'
import { exposureAt } from '@/lib/incident'
import { count, duration, elapsed, percent, rupees } from '@/lib/format'

/**
 * The ledger inset -- warm passbook paper against the dark chrome, and the
 * only place in the product where money appears.
 *
 * Every figure is measured from recorded transactions at the current replay
 * minute. Nothing here is projected or modelled: the interdiction comparison
 * needs the Phase 4 solver, and until that exists this panel says so rather
 * than showing a number that cannot be defended.
 */

interface Props {
  scenario: Scenario
  graph: IncidentGraph
  minute: number
}

function Figure({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'lost' | 'risk' | 'plain'
}) {
  const color =
    tone === 'lost' ? 'text-burn' : tone === 'risk' ? 'text-flow' : 'text-paper-text'
  return (
    <div>
      <div className={`font-mono tabular-nums text-[23px] leading-none ${color}`}>
        {value}
      </div>
      <div className="text-[11px] text-paper-text/60 mt-1.5 leading-tight">{label}</div>
    </div>
  )
}

export default function LedgerInset({ scenario, graph, minute }: Props) {
  const exposure = useMemo(
    () => exposureAt(graph, minute, scenario.amount_inr),
    [graph, minute, scenario.amount_inr],
  )

  const gone = scenario.amount_inr - exposure.stillInside
  const goneShare = scenario.amount_inr > 0 ? gone / scenario.amount_inr : 0
  const reported = minute >= scenario.complaint_delay_minutes

  return (
    <div className="ledger px-6 py-5">
      <div className="flex items-baseline justify-between mb-4">
        <h2 className="font-display text-[15px] text-paper-text tracking-display">
          Incident ledger
        </h2>
        <span className="font-mono text-[11px] text-paper-text/55">
          {elapsed(minute)} · measured from recorded transactions
        </span>
      </div>

      <div className="grid grid-cols-4 gap-6">
        <Figure label="Amount stolen" value={rupees(scenario.amount_inr)} />
        <Figure
          label="Still inside the banking system"
          value={rupees(exposure.stillInside)}
          tone="risk"
        />
        <Figure label="Gone — beyond recovery" value={rupees(gone)} tone="lost" />
        <Figure
          label="Mule accounts reached so far"
          value={count(exposure.mulesReached)}
        />
      </div>

      {/* The drain. Amber is what could still be saved; crimson is what cannot. */}
      <div className="mt-4">
        <div className="h-2 w-full bg-flow rounded-full overflow-hidden flex">
          <div
            className="h-full bg-burn transition-[width] duration-150 ease-linear"
            style={{ width: `${Math.min(100, goneShare * 100)}%` }}
          />
        </div>
        <div className="flex justify-between mt-1.5 text-[11px] text-paper-text/60">
          <span>{percent(1 - goneShare)} still recoverable</span>
          <span>{percent(goneShare)} out of reach</span>
        </div>
      </div>

      <div className="mt-5 pt-4 border-t border-paper-line grid grid-cols-4 gap-6">
        <div>
          <span className="font-mono text-[13px] text-paper-text">
            {exposure.firstExitMinute === null
              ? 'not yet'
              : duration(exposure.firstExitMinute)}
          </span>
          <div className="text-[11px] text-paper-text/55 mt-0.5">
            until the first rupee left
          </div>
        </div>

        <div>
          <span
            className={`font-mono text-[13px] ${
              reported ? 'text-paper-text' : 'text-paper-text/45'
            }`}
          >
            {duration(scenario.complaint_delay_minutes)}
          </span>
          <div className="text-[11px] text-paper-text/55 mt-0.5">
            {reported ? 'complaint filed — banks can act' : 'nobody knows yet'}
          </div>
        </div>

        <div>
          <span className="font-mono text-[13px] text-paper-text">
            {exposure.banksTouched}
          </span>
          <div className="text-[11px] text-paper-text/55 mt-0.5">
            banks the money crossed
          </div>
        </div>

        <div>
          <span className="font-mono text-[13px] text-paper-text">
            {exposure.exitsUsed}
          </span>
          <div className="text-[11px] text-paper-text/55 mt-0.5">
            cash-out points used
          </div>
        </div>
      </div>

      <div className="mt-4 pt-4 border-t border-paper-line flex items-start gap-2.5">
        <Lock size={13} strokeWidth={2} className="text-paper-text/45 mt-0.5 shrink-0" aria-hidden />
        <p className="text-[11.5px] text-paper-text/70 leading-relaxed">
          <span className="text-paper-text">
            This is what happens today, with nobody intervening.
          </span>{' '}
          In Phase 4 this panel splits: current bank practice on the left, Chakravyuh on
          the right, with recovered rupees and innocent accounts frozen under each.
        </p>
      </div>
    </div>
  )
}
