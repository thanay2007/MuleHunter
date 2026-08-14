import { Lock } from 'lucide-react'
import RecoveryCounter from '@/components/console/RecoveryCounter'
import { count, percent, rupees } from '@/lib/format'
import type { ReplayFrame, ReplayHeader } from '@/hooks/useReplayStream'

/**
 * The ledger inset: current bank practice on the left, Chakravyuh on the right.
 *
 * The only panel in the product where money appears, and the only warm surface
 * in a cold interface. Rupees live on paper; the network lives in the dark.
 *
 * Both columns are read from the same WebSocket frame, so the two sides are
 * always the same simulated minute of the same incident. The headline is what
 * *left the banking system*, because that is the figure nobody can argue with:
 * money that has been withdrawn as cash is gone, and no amount of freezing
 * accounts afterwards brings it back.
 */

interface Props {
  frame: ReplayFrame | null
  header: ReplayHeader | null
  amountInr: number
  innocentFrozen: number
  baselineInnocentFrozen: number
}

function Column({
  title,
  subtitle,
  leaked,
  saved,
  innocent,
  frozen,
  amount,
  emphasis,
}: {
  title: string
  subtitle: string
  leaked: number
  saved: number
  innocent: number
  frozen: number
  amount: number
  emphasis: boolean
}) {
  const lostShare = amount > 0 ? leaked / amount : 0

  return (
    <div className={emphasis ? '' : 'opacity-90'}>
      <div className="flex items-baseline justify-between mb-2">
        <h3
          className={`font-display text-[13px] tracking-display ${
            emphasis ? 'text-paper-text' : 'text-paper-text/70'
          }`}
        >
          {title}
        </h3>
        <span className="text-[10.5px] text-paper-text/50">{subtitle}</span>
      </div>

      <div className="flex items-end gap-5">
        <div>
          <RecoveryCounter
            value={saved}
            className={`text-[28px] leading-none block ${
              emphasis ? 'text-interdict' : 'text-paper-text/70'
            }`}
          />
          <div className="text-[10.5px] text-paper-text/60 mt-1">
            kept inside the banking system
          </div>
        </div>
        <div className="ml-auto text-right">
          <div className="font-mono tabular-nums text-[16px] text-burn leading-none">
            {rupees(leaked)}
          </div>
          <div className="text-[10.5px] text-paper-text/60 mt-1">
            gone — {percent(lostShare, 0)} of the theft
          </div>
        </div>
      </div>

      {/* The drain: teal is what was kept, crimson what was not. */}
      <div className="mt-2.5 h-1.5 w-full bg-paper-line rounded-full overflow-hidden flex">
        <div
          className="h-full bg-interdict transition-[width] duration-150 ease-linear"
          style={{ width: `${Math.max(0, Math.min(100, (1 - lostShare) * 100))}%` }}
        />
        <div className="h-full flex-1 bg-burn" />
      </div>

      <div className="mt-2.5 flex items-baseline gap-4 text-[11px]">
        <span className="text-paper-text/70">
          {count(frozen)} frozen
        </span>
        <span className="ml-auto text-paper-text/70">
          innocent frozen{' '}
          <span
            className={`font-mono tabular-nums text-[13px] ${
              innocent > 0 ? 'text-burn' : 'text-paper-text'
            }`}
          >
            {count(innocent)}
          </span>
        </span>
      </div>
    </div>
  )
}

export default function SplitCompare({
  frame,
  header,
  amountInr,
  innocentFrozen,
  baselineInnocentFrozen,
}: Props) {
  if (!frame || !header) {
    return (
      <div className="ledger px-6 py-8 text-center">
        <p className="text-[13px] text-paper-text/60">
          Run the interdiction to compare current practice against Chakravyuh.
        </p>
      </div>
    )
  }

  const ours = frame.at_risk_inr + frame.recovered_inr
  const theirs = frame.baseline.at_risk_inr + frame.baseline.recovered_inr
  const gap = ours - theirs
  const multiple = theirs > 0 ? ours / theirs : null

  return (
    <div className="ledger px-5 py-4">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="font-display text-[14px] text-paper-text tracking-display">
          Incident ledger
        </h2>
        <span className="font-mono text-[10.5px] text-paper-text/55">
          ₹{amountInr.toLocaleString('en-IN')} stolen · replayed against the
          recorded timeline
        </span>
      </div>

      <div className="grid grid-cols-2 gap-8">
        <Column
          title="Current practice"
          subtitle="freeze the named account"
          leaked={frame.baseline.leaked_inr}
          saved={theirs}
          innocent={baselineInnocentFrozen}
          frozen={frame.baseline.frozen.length}
          amount={amountInr}
          emphasis={false}
        />
        <div className="relative">
          {/* Hairline rule, 1px, never 2px. */}
          <div className="absolute -left-4 top-0 bottom-0 w-px bg-paper-line" />
          <Column
            title="Chakravyuh"
            subtitle="freeze frontier"
            leaked={frame.leaked_inr}
            saved={ours}
            innocent={innocentFrozen}
            frozen={frame.frozen.length}
            amount={amountInr}
            emphasis
          />
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-paper-line flex items-center gap-2.5">
        <Lock
          size={13}
          strokeWidth={2}
          className="text-paper-text/45 shrink-0"
          aria-hidden
        />
        <p className="text-[11.5px] text-paper-text/80 leading-relaxed">
          {gap > 0 ? (
            <>
              <span className="font-mono tabular-nums text-paper-text">
                {rupees(gap)}
              </span>{' '}
              more of this victim&rsquo;s money is still inside the banking system
              {multiple !== null && multiple > 1.05 && (
                <>
                  {' '}
                  &mdash;{' '}
                  <span className="font-mono tabular-nums text-paper-text">
                    {multiple.toFixed(1)}&times;
                  </span>{' '}
                  what current practice recovers
                </>
              )}
              .
            </>
          ) : (
            'No advantage on this incident — the money was already gone before anyone could act.'
          )}
        </p>
      </div>
    </div>
  )
}
