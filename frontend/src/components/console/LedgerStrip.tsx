import { ChevronUp } from 'lucide-react'
import { percent, rupees } from '@/lib/format'
import type { ReplayFrame } from '@/hooks/useReplayStream'

/**
 * The ledger reduced to a single line, for when the graph has the screen.
 *
 * Collapsing the comparison must not mean losing it. The two figures that
 * carry the argument -- what each side kept -- stay on paper and stay visible,
 * because a judge glancing at the screen mid-replay should still be able to
 * read who is winning.
 */

interface Props {
  frame: ReplayFrame | null
  amountInr: number
  onExpand: () => void
}

export default function LedgerStrip({ frame, amountInr, onExpand }: Props) {
  const ours = frame ? frame.at_risk_inr + frame.recovered_inr : 0
  const theirs = frame ? frame.baseline.at_risk_inr + frame.baseline.recovered_inr : 0
  const multiple = theirs > 0 ? ours / theirs : null
  const keptShare = amountInr > 0 ? ours / amountInr : 0

  return (
    <div className="ledger px-4 py-2 flex items-center gap-5">
      {frame ? (
        <>
          <div className="flex items-baseline gap-2 min-w-0">
            <span className="text-[12px] text-paper-text/55 shrink-0">
              banks today
            </span>
            <span className="font-mono tabular-nums text-[15.5px] text-interdict">
              {rupees(theirs)}
            </span>
          </div>

          <div className="w-px self-stretch" style={{ background: 'rgba(42,38,32,0.15)' }} />

          <div className="flex items-baseline gap-2 min-w-0">
            <span className="text-[12px] text-paper-text/55 shrink-0">chakravyuh</span>
            <span className="font-mono tabular-nums text-[15.5px] text-interdict">
              {rupees(ours)}
            </span>
          </div>

          {multiple !== null && multiple > 1.05 && (
            <span className="font-mono tabular-nums text-[15.5px] text-interdict shrink-0">
              {multiple.toFixed(1)}×
            </span>
          )}

          {/* A single drain bar for the whole incident, so the split still
              reads at a glance without the full panel. */}
          <div
            className="flex-1 min-w-[80px] h-2 rounded-full overflow-hidden flex"
            style={{ boxShadow: 'inset 0 0 0 1px rgba(42, 38, 32, 0.14)' }}
            role="img"
            aria-label={`${percent(keptShare, 0)} of the stolen money still saved`}
          >
            <div
              className="h-full bg-interdict transition-[width] duration-150 ease-linear"
              style={{ width: `${Math.max(0, Math.min(100, keptShare * 100))}%` }}
            />
            <div className="h-full flex-1 bg-burn" />
          </div>
        </>
      ) : (
        <span className="flex-1 text-[13px] text-paper-text/55">
          Run it to compare how banks work today against Chakravyuh.
        </span>
      )}

      <button
        type="button"
        onClick={onExpand}
        className="shrink-0 flex items-center gap-1.5 text-[12px] text-paper-text/60 hover:text-paper-text transition-colors"
      >
        <ChevronUp size={13} strokeWidth={2} aria-hidden />
        Show details
      </button>
    </div>
  )
}
