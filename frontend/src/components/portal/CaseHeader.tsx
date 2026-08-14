import { useQuery } from '@tanstack/react-query'
import { api, type Scenario } from '@/api/client'
import { useChrome } from '@/i18n/useChrome'
import { rupees } from '@/lib/format'
import type { RunPhase } from '@/store/console'

/**
 * The case docket, replacing the thin scenario strip.
 *
 * A desk works a numbered case against a complaint reference, not "S1". The
 * five fields are the ones an operator would actually be looking at, and they
 * are the same strings the freeze order and the audit trail quote, because all
 * three read them from the backend rather than formatting their own.
 *
 * COLOUR: this panel sits on the operations canvas, so it uses the canvas
 * tokens -- ink, hairlines, hi and lo. The navy institutional palette stops at
 * the frame and does not come down here, and the three money colours are not
 * available to it either. Urgency is carried by weight and fill, not by hue.
 */

interface Props {
  scenario: Scenario | null
  phase: RunPhase
  /** Current replay minute, measured from the fraud. */
  minute: number
  /** View controls that belong to the case, docked to the right of the grid. */
  actions?: React.ReactNode
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] tracking-[0.1em] text-lo/80 uppercase truncate">
        {label}
      </dt>
      <dd className="text-[13px] text-hi truncate mt-0.5">{value}</dd>
    </div>
  )
}

/**
 * The golden-hour meter.
 *
 * The Benchmark tab already proves that complaint delay is the single most
 * important variable in the whole system. This puts that fact on the operator's
 * screen as a countdown, where it does the work it should: making it obvious
 * that the expensive thing is time, not compute.
 */
function GoldenHour({
  elapsed,
  complaintMinute,
  horizon,
}: {
  elapsed: number
  complaintMinute: number
  horizon: number
}) {
  const t = useChrome()
  const remaining = Math.max(0, horizon - elapsed)
  const clamp = (minute: number) => Math.max(0, Math.min(1, minute / horizon))

  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <span className="font-mono text-[12px] text-hi tabular-nums">
          T+{elapsed}
        </span>
        <span className="text-[11.5px] text-lo truncate">
          {remaining > 0 ? (
            <>
              <span className="font-mono text-hi tabular-nums">{remaining} min</span>{' '}
              {t.windowRemaining}
            </>
          ) : (
            t.windowClosed
          )}
        </span>
      </div>

      <div className="relative h-1.5 rounded-full bg-ink overflow-hidden border border-ink-line">
        {/* Time already spent. Grey, because spent time is not a money figure
            and must not borrow one of the three reserved colours. */}
        <div
          className="absolute inset-y-0 left-0 bg-lo/45"
          style={{ width: `${clamp(elapsed) * 100}%` }}
        />
      </div>

      {/* The complaint moment, marked on the same scale. */}
      <div className="relative h-3">
        <span
          className="absolute top-0 -translate-x-1/2 flex flex-col items-center"
          style={{ left: `${clamp(complaintMinute) * 100}%` }}
        >
          <span className="w-px h-1 bg-lo/60" aria-hidden />
          <span className="text-[9.5px] text-lo/70 leading-none whitespace-nowrap mt-px">
            {t.complaintFiled}
          </span>
        </span>
      </div>
    </div>
  )
}

/** Driven straight off the run phase already in the console store. */
function StatusPill({ phase }: { phase: RunPhase }) {
  const t = useChrome()
  const active = phase !== 'idle'
  const label =
    phase === 'done'
      ? t.statusExecuted
      : active
        ? t.statusUnderInterdiction
        : t.statusAwaiting

  return (
    <span
      className={[
        'inline-block px-2 py-0.5 rounded-panel border text-[10.5px] tracking-[0.08em] whitespace-nowrap',
        active ? 'text-hi border-hi/40' : 'text-lo border-ink-line',
      ].join(' ')}
    >
      {label}
    </span>
  )
}

export default function CaseHeader({ scenario, phase, minute, actions }: Props) {
  const t = useChrome()
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: api.health })

  if (!scenario) {
    return (
      <div className="shrink-0 px-5 py-2 border-b border-ink-line flex items-center justify-between gap-4">
        <span className="text-[13px] text-lo">Pick a case to begin</span>
        {actions}
      </div>
    )
  }

  // Before the replay starts the clock still stands at the complaint, because
  // that is genuinely where the case is: the money left 42 minutes ago whether
  // or not anybody has pressed Run.
  const elapsed = Math.max(scenario.complaint_delay_minutes, minute)
  const horizon = health?.golden_hour_minutes ?? scenario.complaint_delay_minutes

  return (
    <div className="shrink-0 px-5 py-2 border-b border-ink-line bg-ink-raised">
      <div className="flex items-start justify-between gap-4">
      <dl className="flex-1 min-w-0 grid grid-cols-[minmax(0,1.3fr)_minmax(0,1.2fr)_minmax(0,0.9fr)_minmax(0,1fr)_minmax(0,1.4fr)] gap-x-5 items-start">
        <Field
          label={t.caseId}
          value={<span className="font-mono text-[12px]">{scenario.case_id}</span>}
        />
        <Field
          label={t.complaintRef}
          value={
            <span className="font-mono text-[12px]">{scenario.complaint_ref}</span>
          }
        />
        <Field
          label={t.amountReported}
          value={
            <span className="font-mono tabular-nums">
              {rupees(scenario.amount_inr)}
            </span>
          }
        />
        <Field
          label={`${t.reportingBank} / ${t.victimDistrict}`}
          value={`${scenario.victim_bank} · ${scenario.victim_district}`}
        />
        <div className="min-w-0">
          <dt className="text-[10px] tracking-[0.1em] text-lo/80 uppercase truncate">
            {t.status}
          </dt>
          <dd className="mt-0.5">
            <StatusPill phase={phase} />
          </dd>
        </div>
      </dl>
      {actions && <div className="shrink-0">{actions}</div>}
      </div>

      <div className="mt-1.5 pt-1.5 border-t border-ink-line">
        <GoldenHour
          elapsed={elapsed}
          complaintMinute={scenario.complaint_delay_minutes}
          horizon={horizon}
        />
      </div>
    </div>
  )
}
