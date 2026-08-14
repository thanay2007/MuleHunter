import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Download,
  FileText,
  Loader2,
  ShieldCheck,
} from 'lucide-react'
import {
  api,
  ApiError,
  freezeOrderPdfUrl,
  type BankOrder,
  type FreezeOrder,
  type OrderParams,
  type OrderRow,
} from '@/api/client'
import { count, rupees } from '@/lib/format'
import { useAudit } from '@/store/audit'
import { useConsole } from '@/store/console'

/**
 * The freeze order: the plan as an instruction to each holding bank.
 *
 * The console shows what to do. This is where it gets issued -- and it is
 * grouped by bank because that is the shape of the real operation: eight
 * institutions each receive their own instruction covering their own accounts.
 *
 * The four-eyes gate is the point of the screen. Instructions the system is
 * not confident about are held back and cannot be downloaded until an operator
 * either approves each one or waives it with a typed reason. That answers
 * "what if the model is wrong" better than any slider, because it shows the
 * system knows *which* of its own recommendations are shaky rather than
 * asserting that none of them are.
 */

interface Approval {
  approved: boolean
  waiver: string
}

/**
 * The offline / empty state.
 *
 * `command` is only shown when running something would actually help. A
 * "start the backend" block under "pick a case first" trains the reader to
 * ignore the instructions on every other screen.
 */
function Missing({ message, command }: { message: string; command?: string }) {
  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="panel p-6 max-w-lg">
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle size={16} className="text-hi" aria-hidden />
          <h2 className="font-display text-base text-hi tracking-display">
            No order to issue
          </h2>
        </div>
        <p className="text-[15.5px] text-lo leading-relaxed">{message}</p>
        {command && (
          <pre className="mt-3 font-mono text-[14px] text-hi bg-ink p-3 rounded-panel border border-ink-line whitespace-pre-wrap">
            {command}
          </pre>
        )}
      </div>
    </div>
  )
}

function ApprovalControl({
  row,
  approval,
  onChange,
}: {
  row: OrderRow
  approval: Approval
  onChange: (next: Approval) => void
}) {
  const [showWaiver, setShowWaiver] = useState(false)
  const waived = approval.waiver.trim().length > 0

  return (
    <div className="mt-1.5 pl-2 border-l border-ink-line">
      <div className="text-[11px] tracking-[0.08em] text-hi mb-1">
        REQUIRES SECOND APPROVAL
      </div>
      <p className="text-[12.5px] text-lo leading-snug mb-1.5">
        {row.p_mule < 0.9
          ? `The detector scores this account ${row.p_mule.toFixed(2)} — below the
             threshold for acting on one officer's authority.`
          : `Freezing this account carries a modelled harm of
             ${row.innocence_cost.toFixed(3)} if the model is wrong about it.`}
      </p>

      <label className="flex items-center gap-2 cursor-pointer text-[13px] text-hi">
        <input
          type="checkbox"
          checked={approval.approved}
          onChange={(event) =>
            onChange({ ...approval, approved: event.target.checked })
          }
          className="accent-[#8A9AAA]"
        />
        Approved by second officer
      </label>

      {!approval.approved && (
        <div className="mt-1.5">
          {showWaiver || waived ? (
            <input
              type="text"
              value={approval.waiver}
              placeholder="Reason for issuing without second approval"
              onChange={(event) =>
                onChange({ ...approval, waiver: event.target.value })
              }
              className="w-full bg-ink border border-ink-line rounded-panel px-2 py-1 text-[12.5px] text-hi placeholder:text-lo/60 focus:outline-none focus:border-hi/40"
            />
          ) : (
            <button
              type="button"
              onClick={() => setShowWaiver(true)}
              className="text-[12.5px] text-lo hover:text-hi underline underline-offset-2"
            >
              or waive with a reason
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function BankPanel({
  bank,
  params,
  approvals,
  onApprove,
  blocked,
}: {
  bank: BankOrder
  params: OrderParams
  approvals: Record<number, Approval>
  onApprove: (rank: number, next: Approval) => void
  blocked: boolean
}) {
  const [open, setOpen] = useState(true)

  return (
    <div className="panel">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown size={14} className="text-lo shrink-0" aria-hidden />
        ) : (
          <ChevronRight size={14} className="text-lo shrink-0" aria-hidden />
        )}
        <span className="font-display text-[15.5px] text-hi tracking-display">
          {bank.bank_name}
        </span>
        <span className="text-[13px] text-lo">
          {count(bank.instructions)}{' '}
          {bank.instructions === 1 ? 'instruction' : 'instructions'}
        </span>
        <span className="font-mono text-[13px] text-hi tabular-nums ml-auto">
          {rupees(bank.amount_at_risk_inr)}
        </span>
        <span className="text-[12px] text-lo">traced</span>
        {bank.requires_second_approval > 0 && (
          <span className="text-[11px] px-1.5 py-0.5 rounded-panel border border-hi/40 text-hi whitespace-nowrap">
            {count(bank.requires_second_approval)} held
          </span>
        )}
      </button>

      {open && (
        <div className="border-t border-ink-line overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-lo">
                {['#', 'Account', 'Instruction', 'Issue', 'Traced', 'Expected', 'p(mule)', 'Why'].map(
                  (heading) => (
                    <th
                      key={heading}
                      className="font-normal text-[11px] tracking-wide uppercase px-3 py-1.5 whitespace-nowrap"
                    >
                      {heading}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {bank.rows.map((row) => (
                <tr key={row.rank} className="border-t border-ink-line align-top">
                  <td className="px-3 py-2 font-mono text-lo tabular-nums">{row.rank}</td>
                  <td className="px-3 py-2 font-mono text-hi whitespace-nowrap">
                    {row.account_ref}
                  </td>
                  <td className="px-3 py-2 text-hi min-w-[190px]">{row.instruction}</td>
                  <td className="px-3 py-2 font-mono text-lo tabular-nums whitespace-nowrap">
                    T+{row.issue_at_minute}
                  </td>
                  <td className="px-3 py-2 font-mono text-hi tabular-nums whitespace-nowrap">
                    {rupees(row.amount_at_risk_inr)}
                  </td>
                  <td className="px-3 py-2 font-mono text-hi tabular-nums whitespace-nowrap">
                    {rupees(row.expected_recovery_inr)}
                  </td>
                  <td className="px-3 py-2 font-mono text-lo tabular-nums">
                    {row.p_mule.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-lo leading-snug min-w-[240px]">
                    {row.reason_codes.join('; ') || '—'}
                    {row.requires_second_approval && (
                      <ApprovalControl
                        row={row}
                        approval={approvals[row.rank] ?? { approved: false, waiver: '' }}
                        onChange={(next) => onApprove(row.rank, next)}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="px-3 py-2 border-t border-ink-line flex items-center gap-2">
            <a
              href={blocked ? undefined : freezeOrderPdfUrl(params, bank.bank_id)}
              aria-disabled={blocked}
              className={[
                'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-panel border text-[13px]',
                blocked
                  ? 'border-ink-line text-lo/50 cursor-not-allowed'
                  : 'border-hi/40 text-hi hover:bg-ink-raised',
              ].join(' ')}
            >
              <Download size={12} aria-hidden />
              {bank.bank_name} instruction (PDF)
            </a>
            <span className="font-mono text-[12px] text-lo">{bank.order_id}</span>
          </div>
        </div>
      )}
    </div>
  )
}

/** Triggers a browser download of text the page generated itself. */
function download(name: string, mime: string, body: string) {
  const url = URL.createObjectURL(new Blob([body], { type: mime }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

function toCsv(order: FreezeOrder): string {
  const head = [
    'bank_id', 'order_id', 'rank', 'account_ref', 'action', 'instruction',
    'issue_at_minute', 'amount_at_risk_inr', 'expected_recovery_inr',
    'p_mule', 'innocence_cost', 'requires_second_approval', 'reason_codes',
  ]
  const escape = (value: string) => `"${value.replace(/"/g, '""')}"`
  const lines = [head.join(',')]
  for (const bank of order.banks) {
    for (const row of bank.rows) {
      lines.push(
        [
          bank.bank_id, bank.order_id, String(row.rank), row.account_ref,
          row.action, escape(row.instruction), String(row.issue_at_minute),
          String(row.amount_at_risk_inr), String(row.expected_recovery_inr),
          row.p_mule.toFixed(4), row.innocence_cost.toFixed(4),
          String(row.requires_second_approval), escape(row.reason_codes.join('; ')),
        ].join(','),
      )
    }
  }
  return lines.join('\n')
}

export default function Orders() {
  const scenarioId = useConsole((s) => s.scenarioId)
  const policy = useConsole((s) => s.policy)
  const budgetK = useConsole((s) => s.budgetK)
  const innocenceBudget = useConsole((s) => s.innocenceBudget)
  const adaptive = useConsole((s) => s.adaptiveAdversary)

  const [approvals, setApprovals] = useState<Record<number, Approval>>({})
  const record = useAudit((s) => s.record)

  // A direct visit to /orders should still work. The console normally sets the
  // case, but bookmarking or reloading this URL must not dead-end.
  const scenariosQuery = useQuery({ queryKey: ['scenarios'], queryFn: api.scenarios })
  const effectiveScenarioId =
    scenarioId ?? scenariosQuery.data?.[0]?.scenario_id ?? null

  const params: OrderParams | null = effectiveScenarioId
    ? {
        scenarioId: effectiveScenarioId,
        policy,
        budgetK,
        innocenceBudget,
        adaptiveAdversary: adaptive,
      }
    : null

  const orderQuery = useQuery({
    queryKey: [
      'freeze-order', effectiveScenarioId, policy, budgetK, innocenceBudget, adaptive,
    ],
    queryFn: () => api.freezeOrder(params as OrderParams),
    enabled: Boolean(params),
  })

  const order = orderQuery.data

  // An instruction clears the gate when a second officer approves it, or when
  // it is waived with a stated reason. Anything else holds the whole order --
  // the download is all-or-nothing on purpose, because a partial order is
  // exactly the sort of thing that gets executed by accident.
  const outstanding = useMemo(() => {
    if (!order) return 0
    let held = 0
    for (const bank of order.banks) {
      for (const row of bank.rows) {
        if (!row.requires_second_approval) continue
        const approval = approvals[row.rank]
        const cleared =
          approval?.approved || (approval?.waiver.trim().length ?? 0) > 0
        if (!cleared) held += 1
      }
    }
    return held
  }, [order, approvals])

  if (scenariosQuery.error) {
    return (
      <Missing
        message={(scenariosQuery.error as Error).message}
        command={'cd backend\nuvicorn app.main:app --reload --port 8000'}
      />
    )
  }
  if (!effectiveScenarioId) {
    return <Missing message="Pick a case on the Active Incident tab first." />
  }
  if (orderQuery.error) {
    const error = orderQuery.error as ApiError
    return (
      <Missing
        message={error.message}
        // Only offer a command when the backend is genuinely unreachable.
        command={
          error.status === 0
            ? 'cd backend\nuvicorn app.main:app --reload --port 8000'
            : undefined
        }
      />
    )
  }
  if (orderQuery.isPending || !order || !params) {
    return (
      <div className="h-full flex items-center justify-center">
        <span className="flex items-center gap-2 text-[15.5px] text-lo">
          <Loader2 size={14} className="animate-spin" aria-hidden />
          Preparing the order…
        </span>
      </div>
    )
  }

  const blocked = outstanding > 0

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[1180px] mx-auto px-6 py-5 space-y-4">
        <header className="panel px-5 py-4">
          <div className="flex items-start justify-between gap-6 flex-wrap">
            <div className="min-w-0">
              <h1 className="font-display text-[19px] text-hi tracking-display">
                Freeze instruction — immediate
              </h1>
              <p className="text-[13px] text-lo mt-1">
                <span className="font-mono">{order.case_id}</span> ·{' '}
                <span className="font-mono">{order.order_id}</span> · issued by{' '}
                {order.issued_by}, {order.issuing_desk}
              </p>
            </div>
            <dl className="flex items-start gap-6 text-[13px]">
              {[
                ['Instructions', count(order.total_instructions)],
                ['Institutions', count(order.banks.length)],
                ['Held for approval', count(order.total_requires_second_approval)],
                ['Basis', order.policy_label],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-[10px] tracking-[0.1em] uppercase text-lo/80">
                    {label}
                  </dt>
                  <dd className="text-hi mt-0.5">{value}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="mt-4 pt-3 border-t border-ink-line flex items-center gap-2 flex-wrap">
            <a
              href={blocked ? undefined : freezeOrderPdfUrl(params)}
              aria-disabled={blocked}
              className={[
                'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-panel border text-[14px]',
                blocked
                  ? 'border-ink-line text-lo/50 cursor-not-allowed'
                  : 'border-hi/40 text-hi hover:bg-ink-raised',
              ].join(' ')}
            >
              <FileText size={13} aria-hidden />
              Download all instructions (PDF)
            </a>
            <button
              type="button"
              disabled={blocked}
              onClick={() => {
                record('export', 'Order exported as CSV', {
                  order: order.order_id,
                  instructions: order.total_instructions,
                })
                download(
                  `freeze-order-${order.scenario_id}.csv`,
                  'text/csv;charset=utf-8',
                  toCsv(order),
                )
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-panel border border-ink-line text-[14px] text-lo hover:text-hi disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download size={13} aria-hidden />
              CSV
            </button>
            <button
              type="button"
              disabled={blocked}
              onClick={() => {
                record('export', 'Order exported as JSON audit bundle', {
                  order: order.order_id,
                  instructions: order.total_instructions,
                })
                download(
                  `freeze-order-${order.scenario_id}.json`,
                  'application/json',
                  JSON.stringify(
                    { order, approvals, generated_by: 'chakravyuh console' },
                    null,
                    2,
                  ),
                )
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-panel border border-ink-line text-[14px] text-lo hover:text-hi disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download size={13} aria-hidden />
              JSON audit bundle
            </button>

            {blocked ? (
              <span className="flex items-center gap-1.5 text-[13px] text-hi">
                <AlertTriangle size={13} aria-hidden />
                {count(outstanding)}{' '}
                {outstanding === 1 ? 'instruction is' : 'instructions are'} held
                pending a second approval.
              </span>
            ) : (
              order.total_requires_second_approval > 0 && (
                <span className="flex items-center gap-1.5 text-[13px] text-lo">
                  <ShieldCheck size={13} aria-hidden />
                  All held instructions cleared.
                </span>
              )
            )}
          </div>
        </header>

        {order.banks.length === 0 ? (
          <div className="panel px-5 py-6">
            <p className="text-[15px] text-lo leading-relaxed">
              This plan is empty, so there is nothing to issue. At a harm limit of
              B = {order.innocence_budget.toFixed(2)} the solver declined to act on
              this case: no available action was worth its modelled cost. Raise the
              harm limit on the Active Incident tab to see what it would do with
              more authority.
            </p>
          </div>
        ) : (
          order.banks.map((bank) => (
            <BankPanel
              key={bank.bank_id}
              bank={bank}
              params={params}
              approvals={approvals}
              blocked={blocked}
              onApprove={(rank, next) => {
                setApprovals((current) => ({ ...current, [rank]: next }))
                // Only the decision is logged, and only when it is made --
                // keystrokes in the waiver box are not an audit event.
                if (next.approved) {
                  record('approval', `Instruction ${rank} approved`, {
                    order: order.order_id,
                    bank: bank.bank_id,
                    rank,
                  })
                }
              }}
            />
          ))
        )}

        {order.total_requires_second_approval === 0 && order.banks.length > 0 && (
          <p className="text-[13px] text-lo leading-relaxed px-1">
            No instruction in this order needs a second signature: the detector
            scored every selected account above the threshold, and none carries
            enough modelled harm to warrant one. That is not always true —{' '}
            <span className="text-hi">One hop downstream</span> on this case
            produces instructions the model believes are innocent, and they are
            held.
          </p>
        )}

        <p className="text-[12px] text-lo/80 leading-relaxed px-1">{order.disclaimer}</p>
      </div>
    </div>
  )
}
