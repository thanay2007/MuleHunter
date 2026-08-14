import RecoveryCounter from '@/components/console/RecoveryCounter'
import { count, elapsed, percent, rupees } from '@/lib/format'
import type { ReplayFrame, ReplayHeader } from '@/hooks/useReplayStream'

/**
 * The ledger inset: current bank practice on the left, Chakravyuh on the right.
 *
 * The only panel in the product where money appears, and the only warm surface
 * in a cold interface. Rupees live on paper; the network lives in the dark.
 *
 * Both columns read from the same WebSocket frame, so the two sides are always
 * the same simulated minute of the same incident. The headline is what *left
 * the banking system*, because that is the figure nobody can argue with: money
 * withdrawn as cash is gone, and no amount of freezing afterwards brings it
 * back.
 *
 * COLOUR DISCIPLINE. Teal means money saved and crimson means money lost --
 * on both sides. It is tempting to tint only our own column and leave the
 * baseline grey, but that colours by who wins rather than by what the money
 * is, and a judge who notices reads it as the design arguing on the product's
 * behalf. The two columns get identical treatment; the gap between the numbers
 * is allowed to make the case by itself.
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
}: {
  title: string
  subtitle: string
  leaked: number
  saved: number
  innocent: number
  frozen: number
  amount: number
}) {
  const lostShare = amount > 0 ? Math.min(1, leaked / amount) : 0
  const keptShare = 1 - lostShare

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <h3 className="font-display text-[13px] text-paper-text tracking-display">
          {title}
        </h3>
        <span className="text-[10.5px] text-paper-text/50">{subtitle}</span>
      </div>

      <RecoveryCounter
        value={saved}
        className="text-[30px] leading-none block text-interdict"
      />
      <div className="text-[11px] text-paper-text/60 mt-1.5">
        kept inside the banking system
      </div>

      {/* The drain: teal is what was kept, crimson what was not. */}
      <div
        className="mt-3 h-2 w-full rounded-full overflow-hidden flex"
        role="img"
        aria-label={`${percent(keptShare, 0)} kept, ${percent(lostShare, 0)} gone`}
      >
        <div
          className="h-full bg-interdict transition-[width] duration-150 ease-linear"
          style={{ width: `${Math.max(0, keptShare * 100)}%` }}
        />
        <div className="h-full flex-1 bg-burn" />
      </div>

      <div className="mt-2.5 flex items-baseline justify-between gap-3">
        <span className="font-mono tabular-nums text-[14px] text-burn leading-none">
          {rupees(leaked)}
        </span>
        <span className="text-[11px] text-paper-text/60">
          gone — {percent(lostShare, 0)} of the theft
        </span>
      </div>

      <div className="mt-3 pt-2.5 border-t border-paper-line flex items-baseline justify-between gap-3 text-[11px] text-paper-text/70">
        <span>
          <span className="font-mono tabular-nums text-paper-text">
            {count(frozen)}
          </span>{' '}
          {frozen === 1 ? 'account frozen' : 'accounts frozen'}
        </span>
        <span>
          <span
            className={`font-mono tabular-nums text-[13px] ${
              innocent > 0 ? 'text-burn' : 'text-paper-text'
            }`}
          >
            {count(innocent)}
          </span>{' '}
          innocent
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
  const extraInnocent = innocentFrozen - baselineInnocentFrozen

  return (
    <div className="ledger px-6 py-5">
      <div className="flex items-baseline justify-between gap-4 mb-4">
        <h2 className="font-display text-[14px] text-paper-text tracking-display">
          Incident ledger
        </h2>
        <span className="text-[10.5px] text-paper-text/55">
          <span className="font-mono tabular-nums text-paper-text/75">
            {rupees(amountInr)}
          </span>{' '}
          stolen ·{' '}
          <span className="font-mono tabular-nums text-paper-text/75">
            {elapsed(frame.minute)}
          </span>{' '}
          into the incident
        </span>
      </div>

      <div className="grid grid-cols-2 gap-10">
        <Column
          title="Current practice"
          subtitle="freeze the named account"
          leaked={frame.baseline.leaked_inr}
          saved={theirs}
          innocent={baselineInnocentFrozen}
          frozen={frame.baseline.frozen.length}
          amount={amountInr}
        />
        <div className="relative">
          {/* Hairline rule, 1px, never 2px. */}
          <div className="absolute -left-5 top-0 bottom-0 w-px bg-paper-line" />
          <Column
            title="Chakravyuh"
            subtitle="freeze frontier"
            leaked={frame.leaked_inr}
            saved={ours}
            innocent={innocentFrozen}
            frozen={frame.frozen.length}
            amount={amountInr}
          />
        </div>
      </div>

      {/* The gap is the entire argument, so it gets the largest figure here. */}
      <div className="mt-5 pt-4 border-t border-paper-line flex items-center gap-6">
        {gap > 0 ? (
          <>
            {multiple !== null && multiple > 1.05 && (
              <div className="shrink-0">
                <div className="font-mono tabular-nums text-[34px] leading-none text-interdict">
                  {multiple.toFixed(1)}×
                </div>
                <div className="text-[10.5px] text-paper-text/60 mt-1">
                  more money kept
                </div>
              </div>
            )}
            <p className="text-[12.5px] text-paper-text/80 leading-relaxed">
              <span className="font-mono tabular-nums text-paper-text">
                {rupees(gap)}
              </span>{' '}
              more of this victim&rsquo;s money is still inside the banking system and
              can be returned to them
              {extraInnocent === 0 ? (
                <>
                  , with{' '}
                  <span className="text-paper-text">
                    no additional innocent accounts frozen
                  </span>
                </>
              ) : extraInnocent > 0 ? (
                <>
                  , at the cost of{' '}
                  <span className="font-mono tabular-nums text-burn">
                    {count(extraInnocent)}
                  </span>{' '}
                  more innocent {extraInnocent === 1 ? 'account' : 'accounts'} frozen
                </>
              ) : (
                <>
                  , while freezing{' '}
                  <span className="font-mono tabular-nums text-paper-text">
                    {count(-extraInnocent)}
                  </span>{' '}
                  fewer innocent {(-extraInnocent) === 1 ? 'account' : 'accounts'}
                </>
              )}
              .
            </p>
          </>
        ) : (
          <p className="text-[12.5px] text-paper-text/80 leading-relaxed">
            No advantage on this incident — the money was already gone before anyone
            could act.
          </p>
        )}
      </div>
    </div>
  )
}
