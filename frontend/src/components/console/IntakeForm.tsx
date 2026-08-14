import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import { api, ApiError, type Scenario } from '@/api/client'
import { rupees } from '@/lib/format'
import { useAudit } from '@/store/audit'
import { useConsole } from '@/store/console'

/**
 * File a complaint the system has never seen.
 *
 * The six scenarios are seeded, which invites the fair question of whether the
 * console is six hardcoded outcomes rather than a working pipeline. This proves
 * it is not: any account in the dataset, any amount, any pair of times, and the
 * same tracing, scoring, rollout and solve run against it.
 *
 * Behind an "Advanced" disclosure on purpose. It is a credibility exhibit for
 * the questions after the demo, not part of the four-minute run, and nobody
 * should stumble into an empty form mid-presentation.
 */

/** Channels the generator actually produces. Not a free-text field. */
const CHANNELS = ['UPI', 'IMPS', 'NEFT', 'CARD'] as const

interface Props {
  /** Used to prefill from a real case, so the form opens ready to submit. */
  scenarios: Scenario[] | undefined
}

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="text-[11px] tracking-[0.08em] uppercase text-lo/80 block mb-0.5">
        {label}
      </span>
      {children}
    </label>
  )
}

const INPUT_CLASS =
  'w-full bg-ink border border-ink-line rounded-panel px-2 py-1 text-[13px] text-hi focus:outline-none focus:border-hi/40'

export default function IntakeForm({ scenarios }: Props) {
  const [open, setOpen] = useState(false)
  const setScenario = useConsole((s) => s.setScenario)
  const addFiledIncident = useConsole((s) => s.addFiledIncident)
  const record = useAudit((s) => s.record)
  const queryClient = useQueryClient()

  // Prefilled from the first seeded case: an empty form on stage is a way to
  // get a validation error in front of an audience.
  const seed = scenarios?.[0]
  const [account, setAccount] = useState('')
  const [amount, setAmount] = useState('500000')
  const [when, setWhen] = useState('')
  const [delay, setDelay] = useState('30')
  const [channel, setChannel] = useState<string>('UPI')

  const victimAccount = account || seed?.victim_account || ''
  // `datetime-local` wants `YYYY-MM-DDTHH:mm`, and the API returns seconds.
  const incidentTime = when || (seed ? seed.incident_time.slice(0, 16) : '')

  const filed = useMutation({
    mutationFn: () =>
      api.intake({
        victim_account: victimAccount,
        amount_inr: Number(amount),
        incident_time: incidentTime,
        complaint_delay_minutes: Number(delay),
        channel,
      }),
    onSuccess: (data) => {
      record('case', `Complaint filed: ${data.case_id}`, {
        victim: data.victim_account,
        bank: data.victim_bank,
        amount_inr: data.amount_inr,
        reported_after_min: data.complaint_delay_minutes,
        accounts_traced: data.accounts_traced,
      })
      // Shaped like a scenario so every panel renders it without a second code
      // path. The fields the intake pipeline genuinely does not know -- which
      // ring this belongs to, how deep it goes -- are left empty rather than
      // invented, and the ring typology reads "reported" because that is all
      // a fresh complaint actually tells us.
      addFiledIncident({
        scenario_id: data.incident_id,
        case_id: data.case_id,
        complaint_ref: data.complaint_ref,
        name: `Filed complaint — ${data.victim_account}`,
        summary: `Reported ${data.complaint_delay_minutes} min after the transfer.`,
        victim_account: data.victim_account,
        victim_bank: data.victim_bank,
        victim_district: data.victim_district,
        victim_archetype: '',
        amount_inr: data.amount_inr,
        complaint_delay_minutes: data.complaint_delay_minutes,
        ring_id: '',
        ring_typology: 'reported',
        secondary_ring_id: null,
        incident_time: data.incident_time,
        complaint_time: data.complaint_time,
        ring_accounts: 0,
        episode_flow_inr: 0,
        hops: 0,
      })
      queryClient.invalidateQueries({ queryKey: ['graph', data.incident_id] })
      setScenario(data.incident_id)
    },
  })

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-[12.5px] text-lo hover:text-hi transition-colors"
      >
        {open ? (
          <ChevronDown size={12} aria-hidden />
        ) : (
          <ChevronRight size={12} aria-hidden />
        )}
        Advanced — file a new complaint
      </button>

      {open && (
        <div className="mt-2 space-y-2">
          <p className="text-[12px] text-lo leading-snug">
            Runs the full pipeline on any account in the dataset, not just the
            six seeded cases.
          </p>

          <Field label="Victim account">
            <input
              className={INPUT_CLASS}
              value={victimAccount}
              onChange={(event) => setAccount(event.target.value)}
              placeholder="AC000123"
              spellCheck={false}
            />
          </Field>

          <div className="grid grid-cols-2 gap-2">
            <Field label="Amount (₹)">
              <input
                className={INPUT_CLASS}
                type="number"
                min={1}
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
              />
            </Field>
            <Field label="Reported after (min)">
              <input
                className={INPUT_CLASS}
                type="number"
                min={0}
                max={1440}
                value={delay}
                onChange={(event) => setDelay(event.target.value)}
              />
            </Field>
          </div>

          <Field label="Time of fraud">
            <input
              className={INPUT_CLASS}
              type="datetime-local"
              value={incidentTime}
              onChange={(event) => setWhen(event.target.value)}
            />
          </Field>

          <Field label="Channel">
            <select
              className={INPUT_CLASS + ' cursor-pointer'}
              value={channel}
              onChange={(event) => setChannel(event.target.value)}
            >
              {CHANNELS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </Field>

          <button
            type="button"
            onClick={() => filed.mutate()}
            disabled={filed.isPending || !victimAccount || !incidentTime}
            className="w-full py-1.5 rounded-panel border border-ink-line text-[13px] text-lo hover:text-hi hover:border-hi/40 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
          >
            {filed.isPending ? (
              <>
                <Loader2 size={12} className="animate-spin" aria-hidden />
                Tracing…
              </>
            ) : (
              'File complaint'
            )}
          </button>

          {/* Specific errors, because the likeliest failure on stage is a judge
              typing an account that does not exist. */}
          {filed.error && (
            <p className="text-[12px] text-hi leading-snug">
              {(filed.error as ApiError).message}
            </p>
          )}

          {filed.data && (
            <p className="text-[12px] text-lo leading-snug">
              Traced{' '}
              <span className="font-mono text-hi">{filed.data.accounts_traced}</span>{' '}
              accounts holding{' '}
              <span className="font-mono text-hi">
                {rupees(filed.data.tainted_still_inside_inr)}
              </span>
              {filed.data.tainted_already_gone_inr > 0 && (
                <>
                  {' · '}
                  <span className="font-mono text-hi">
                    {rupees(filed.data.tainted_already_gone_inr)}
                  </span>{' '}
                  already gone
                </>
              )}
              . Press Run interdiction.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
