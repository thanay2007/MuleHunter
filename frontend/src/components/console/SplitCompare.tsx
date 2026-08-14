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
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-3 mb-3.5">
        <h3 className="font-display text-[13px] text-paper-text tracking-display">
          {title}
        </h3>
        <span className="text-[10px] text-paper-text/45 tracking-wide">{subtitle}</span>
      </div>

      <RecoveryCounter
        value={saved}
        className="text-[32px] leading-none block text-interdict"
      />
      <div className="text-[11px] text-paper-text/55 mt-2">
        kept inside the banking system
      </div>

      {/* The drain: teal is what was kept, crimson what was not. */}
      <div
        className="mt-3.5 h-2.5 w-full rounded-full overflow-hidden flex"
        style={{ boxShadow: 'inset 0 0 0 1px rgba(42, 38, 32, 0.14)' }}
        role="img"
        aria-label={`${percent(keptShare, 0)} kept, ${percent(lostShare, 0)} gone`}
      >
        <div
          className="h-full bg-interdict transition-[width] duration-150 ease-linear"
          style={{ width: `${Math.max(0, keptShare * 100)}%` }}
        />
        <div className="h-full flex-1 bg-burn" />
      </div>

      <div className="mt-3 flex items-baseline justify-between gap-3">
        <span className="font-mono tabular-nums text-[15px] text-burn leading-none">
          {rupees(leaked)}
        </span>
        <span className="text-[11px] text-paper-text/55">
          gone — {percent(lostShare, 0)} of the theft
        </span>
      </div>

      <div
        className="mt-3.5 pt-3 flex items-baseline justify-between gap-3 text-[11px] text-paper-text/60"
        style={{ borderTop: '1px solid rgba(42, 38, 32, 0.13)' }}
      >
        <span>
          <span className="font-mono tabular-nums text-paper-text">{count(frozen)}</span>{' '}
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
      <div className="ledger px-6 py-9 text-center">
        <p className="text-[13px] text-paper-text/55">
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

  // Nothing has left yet on either side. Early in the replay this is the normal
  // state, and it must not be reported as "no advantage" -- there is simply no
  // outcome to compare so far.
  const anythingLost = frame.leaked_inr > 0 || frame.baseline.leaked_inr > 0

  return (
    <div className="ledger px-7 py-6">
      <div
        className="flex items-baseline justify-between gap-4 pb-3.5 mb-5"
        style={{ borderBottom: '1px solid rgba(42, 38, 32, 0.13)' }}
      >
        <h2 className="font-display text-[14px] text-paper-text tracking-display">
          Incident ledger
        </h2>
        <span className="text-[10.5px] text-paper-text/50">
          <span className="font-mono tabular-nums text-paper-text/70">
            {rupees(amountInr)}
          </span>{' '}
          stolen ·{' '}
          <span className="font-mono tabular-nums text-paper-text/70">
            {elapsed(frame.minute)}
          </span>{' '}
          into the incident
        </span>
      </div>

      <div className="grid grid-cols-2 gap-12">
        <Column
          title="Current practice"
          subtitle="freeze the named account"
          leaked={frame.baseline.leaked_inr}
          saved={theirs}
          innocent={baselineInnocentFrozen}
          frozen={frame.baseline.frozen.length}
          amount={amountInr}
        />
        <div className="relative min-w-0">
          {/* Hairline rule, 1px, never 2px. */}
          <div
            className="absolute -left-6 top-0 bottom-0 w-px"
            style={{ background: 'rgba(42, 38, 32, 0.15)' }}
          />
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
      <div
        className="mt-6 pt-5 flex items-center gap-6"
        style={{ borderTop: '1px solid rgba(42, 38, 32, 0.13)' }}
      >
        {!anythingLost ? (
          <p className="text-[12.5px] text-paper-text/70 leading-relaxed">
            Nothing has left the banking system yet — every rupee is still
            recoverable on both sides.
          </p>
        ) : gap > 0 ? (
          <>
            {multiple !== null && multiple > 1.05 && (
              <div
                className="shrink-0 px-4 py-2.5 text-center rounded-[2px]"
                style={{ border: '1px solid rgba(47, 191, 184, 0.45)' }}
              >
                <div className="font-mono tabular-nums text-[32px] leading-none text-interdict">
                  {multiple.toFixed(1)}×
                </div>
                <div className="text-[9.5px] text-paper-text/50 mt-1.5 tracking-wide">
                  more money kept
                </div>
              </div>
            )}
            <p className="text-[12.5px] text-paper-text/75 leading-relaxed">
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
                  fewer innocent {-extraInnocent === 1 ? 'account' : 'accounts'}
                </>
              )}
              .
            </p>
          </>
        ) : (
          <p className="text-[12.5px] text-paper-text/70 leading-relaxed">
            No advantage on this incident — the money was already gone before anyone
            could act.
          </p>
        )}
      </div>
    </div>
  )
}
