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
  /** The adaptive-adversary run, reported under our own column and nowhere
   *  else -- it is a caveat on our result, not on current practice. */
  adversary: AdversaryNote | null
  /**
   * Docked into a narrow column rather than spread across the bottom. The two
   * sides stack vertically, and the divider turns from a vertical hairline into
   * a horizontal one.
   */
  dense?: boolean
}

export interface AdversaryNote {
  /** Transfers the operator pushed down another path after we blocked one. */
  reroutedTransfers: number
  /** Recovery under this run: prevented rupees over rupees stolen. */
  recoveryShare: number
  /**
   * The same case under a passive adversary, if this console has run it. Null
   * until it has -- an unproven arrow is worse than no arrow.
   */
  passiveRecoveryShare: number | null
}

/**
 * What the adaptive adversary cost us, stated plainly under our own column.
 *
 * Crimson is money lost, and that is exactly what this sentence reports, so it
 * is inside the colour language rather than an exception to it. It is drawn as
 * an outline instead of a fill because it annotates the result above it; a
 * solid crimson block would read as a fourth money figure.
 */
function AdversaryCaption({ note }: { note: AdversaryNote }) {
  const { reroutedTransfers, recoveryShare, passiveRecoveryShare } = note
  return (
    <p
      className="mt-2.5 px-2 py-1 rounded-[2px] text-[12.5px] text-paper-text/75 leading-snug"
      style={{ border: '1px solid rgba(200, 68, 62, 0.5)' }}
    >
      <span className="font-mono tabular-nums text-paper-text">
        {count(reroutedTransfers)}
      </span>{' '}
      {reroutedTransfers === 1 ? 'transfer' : 'transfers'} rerouted
      {passiveRecoveryShare !== null && (
        <>
          {' · recovery '}
          <span className="font-mono tabular-nums text-paper-text">
            {percent(passiveRecoveryShare, 0)}
          </span>
          {' → '}
          <span className="font-mono tabular-nums text-burn">
            {percent(recoveryShare, 0)}
          </span>
        </>
      )}
    </p>
  )
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
      <div className="flex items-baseline justify-between gap-3 mb-2.5">
        <h3 className="font-display text-[15.5px] text-paper-text tracking-display">
          {title}
        </h3>
        <span className="text-[12px] text-paper-text/45 tracking-wide">{subtitle}</span>
      </div>

      <RecoveryCounter
        value={saved}
        className="text-[33.5px] leading-none block text-interdict"
      />
      <div className="text-[13px] text-paper-text/55 mt-2">
        saved — still in the bank
      </div>

      {/* The drain: teal is what was kept, crimson what was not. */}
      <div
        className="mt-2.5 h-2.5 w-full rounded-full overflow-hidden flex"
        style={{ boxShadow: 'inset 0 0 0 1px rgba(42, 38, 32, 0.14)' }}
        role="img"
        aria-label={`${percent(keptShare, 0)} saved, ${percent(lostShare, 0)} lost`}
      >
        <div
          className="h-full bg-interdict transition-[width] duration-150 ease-linear"
          style={{ width: `${Math.max(0, keptShare * 100)}%` }}
        />
        <div className="h-full flex-1 bg-burn" />
      </div>

      <div className="mt-2 flex items-baseline justify-between gap-3">
        <span className="font-mono tabular-nums text-[17.5px] text-burn leading-none">
          {rupees(leaked)}
        </span>
        <span className="text-[13px] text-paper-text/55">
          lost — {percent(lostShare, 0)} of the total
        </span>
      </div>

      <div
        className="mt-2.5 pt-2.5 flex items-baseline justify-between gap-3 text-[13px] text-paper-text/60"
        style={{ borderTop: '1px solid rgba(42, 38, 32, 0.13)' }}
      >
        <span>
          <span className="font-mono tabular-nums text-paper-text">{count(frozen)}</span>{' '}
          {frozen === 1 ? 'account frozen' : 'accounts frozen'}
        </span>
        <span>
          <span
            className={`font-mono tabular-nums text-[15.5px] ${
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
  adversary,
  dense = false,
}: Props) {
  if (!frame || !header) {
    return (
      <div className="ledger px-6 py-9 text-center">
        <p className="text-[15.5px] text-paper-text/55">
          Run it to compare how banks work today against Chakravyuh.
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
    <div className="ledger px-6 py-4">
      <div
        className="flex items-baseline justify-between gap-4 pb-3 mb-4"
        style={{ borderBottom: '1px solid rgba(42, 38, 32, 0.13)' }}
      >
        <h2 className="font-display text-[16.5px] text-paper-text tracking-display">
          Where the money ended up
        </h2>
        <span className="text-[12.5px] text-paper-text/50">
          <span className="font-mono tabular-nums text-paper-text/70">
            {rupees(amountInr)}
          </span>{' '}
          stolen ·{' '}
          <span className="font-mono tabular-nums text-paper-text/70">
            {elapsed(frame.minute)}
          </span>{' '}
          in
        </span>
      </div>

      <div className={dense ? 'flex flex-col gap-6' : 'grid grid-cols-2 gap-12'}>
        <Column
          title="Current practice"
          subtitle="freezes one account"
          leaked={frame.baseline.leaked_inr}
          saved={theirs}
          innocent={baselineInnocentFrozen}
          frozen={frame.baseline.frozen.length}
          amount={amountInr}
        />
        <div className={dense ? 'relative min-w-0 pt-6' : 'relative min-w-0'}>
          {/* Hairline rule, 1px, never 2px. Vertical between columns when the
              panel is wide; horizontal between rows when it is docked. */}
          <div
            className={
              dense ? 'absolute left-0 right-0 top-0 h-px' : 'absolute -left-6 top-0 bottom-0 w-px'
            }
            style={{ background: 'rgba(42, 38, 32, 0.15)' }}
          />
          <Column
            title="Chakravyuh"
            subtitle="freezes the best set"
            leaked={frame.leaked_inr}
            saved={ours}
            innocent={innocentFrozen}
            frozen={frame.frozen.length}
            amount={amountInr}
          />
          {adversary && <AdversaryCaption note={adversary} />}
        </div>
      </div>

      {/* The gap is the entire argument, so it gets the largest figure here. */}
      <div
        className={[
          'mt-4 pt-4 gap-5',
          dense ? 'flex flex-col items-start' : 'flex items-center gap-6',
        ].join(' ')}
        style={{ borderTop: '1px solid rgba(42, 38, 32, 0.13)' }}
      >
        {!anythingLost ? (
          <p className="text-[15px] text-paper-text/70 leading-relaxed">
            No money has left the banks yet. All of it can still be saved.
          </p>
        ) : gap > 0 ? (
          <>
            {multiple !== null && multiple > 1.05 && (
              <div
                className="shrink-0 px-4 py-2.5 text-center rounded-[2px]"
                style={{ border: '1px solid rgba(47, 191, 184, 0.45)' }}
              >
                <div className="font-mono tabular-nums text-[33.5px] leading-none text-interdict">
                  {multiple.toFixed(1)}×
                </div>
                <div className="text-[11px] text-paper-text/50 mt-1.5 tracking-wide">
                  more saved
                </div>
              </div>
            )}
            <p className="text-[15px] text-paper-text/75 leading-relaxed">
              <span className="font-mono tabular-nums text-paper-text">
                {rupees(gap)}
              </span>{' '}
              more of the victim&rsquo;s money is saved and can be given back
              {extraInnocent === 0 ? (
                <>
                  , with{' '}
                  <span className="text-paper-text">
                    no extra innocent accounts frozen
                  </span>
                </>
              ) : extraInnocent > 0 ? (
                <>
                  , but it froze{' '}
                  <span className="font-mono tabular-nums text-burn">
                    {count(extraInnocent)}
                  </span>{' '}
                  more innocent {extraInnocent === 1 ? 'account' : 'accounts'}
                </>
              ) : (
                <>
                  , and it froze{' '}
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
          <p className="text-[15px] text-paper-text/70 leading-relaxed">
            No gain here — the money was gone before anyone could act.
          </p>
        )}
      </div>
    </div>
  )
}
