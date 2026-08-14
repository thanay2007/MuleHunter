import { Snowflake, ShieldAlert, UserCheck } from 'lucide-react'
import type { FreezeAction, PlanStep } from '@/api/client'
import { elapsed, rupeesCompact } from '@/lib/format'

/**
 * The issued plan, in the order it goes out.
 *
 * Order is a decision, not a presentation choice. Instructions take time to
 * reach a holding bank and only a few go out at once, so the fifth freeze
 * lands minutes after the first and intercepts strictly less money. The queue
 * shows the issue time for exactly that reason.
 *
 * Rows are dimmed until the replay clock reaches their issue minute, so the
 * queue works down in step with the canvas.
 */

const ACTION_META: Record<
  FreezeAction,
  { label: string; icon: typeof Snowflake; hint: string }
> = {
  full_freeze: {
    label: 'Full freeze',
    icon: Snowflake,
    hint: 'Nothing moves in or out',
  },
  outbound_hold: {
    label: 'Outbound hold',
    icon: ShieldAlert,
    hint: 'Money can come in, but not go out',
  },
  step_up_verification: {
    label: 'Extra ID check',
    icon: UserCheck,
    hint: 'Prove who you are before money leaves',
  },
}

interface Props {
  plan: PlanStep[]
  minute: number
  selectedId: string | null
  onSelect: (accountId: string) => void
}

export default function FreezeQueue({
  plan,
  minute,
  selectedId,
  onSelect,
}: Props) {
  if (plan.length === 0) {
    return (
      <p className="text-[14px] text-lo leading-relaxed">
        No plan yet. Run it to see which accounts to freeze, and in what order.
      </p>
    )
  }

  return (
    <ol className="space-y-1">
      {plan.map((step) => {
        const issued = minute >= step.issue_at_minute
        const meta = ACTION_META[step.action]
        const Icon = meta.icon
        const selected = step.account_id === selectedId

        return (
          <li key={step.account_id}>
            <button
              type="button"
              onClick={() => onSelect(step.account_id)}
              aria-current={selected ? 'true' : undefined}
              className={[
                'w-full text-left px-2 py-1.5 rounded-panel border transition-colors',
                selected
                  ? 'border-hi/40 bg-ink-raised'
                  : 'border-transparent hover:bg-ink-raised',
                issued ? 'opacity-100' : 'opacity-45',
              ].join(' ')}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-[13px] text-lo w-5 shrink-0 tabular-nums">
                  {step.rank}
                </span>
                <Icon
                  size={12}
                  className={issued ? 'text-interdict shrink-0' : 'text-lo shrink-0'}
                  aria-hidden
                />
                <span className="font-mono text-[14px] text-hi truncate">
                  {step.account_id}
                </span>
                <span className="font-mono text-[13px] text-lo ml-auto shrink-0 tabular-nums">
                  {rupeesCompact(step.marginal_recovery_inr)}
                </span>
              </div>
              <div className="flex items-center gap-2 mt-0.5 pl-7">
                <span className="text-[12.5px] text-lo">{step.bank}</span>
                <span className="text-[12.5px] text-lo" title={meta.hint}>
                  {meta.label}
                </span>
                <span className="font-mono text-[12.5px] text-lo ml-auto tabular-nums">
                  {elapsed(step.issue_at_minute)}
                </span>
              </div>
            </button>
          </li>
        )
      })}
    </ol>
  )
}
