import { useConsole } from '@/store/console'
import { controls } from '@/theme/tokens'
import type { FreezeAction, PlanStep } from '@/api/client'

/**
 * The two budgets the operator actually controls.
 *
 * These are not settings, they are the policy question. K is how much freeze
 * authority is available; B is how much collateral harm is acceptable to spend
 * it. Moving B is the answer to "what if your classifier is wrong" -- tighten
 * it and the solver switches from full freezes to outbound holds and step-up
 * verification rather than simply freezing fewer accounts.
 *
 * Which is why B is worth this much machinery. A linear 0.05-8 range put every
 * regime change in the leftmost 6% of the rail, so the control that carries the
 * argument felt dead. The travel is warped instead, and what changes underneath
 * it -- the *composition* of the plan, not its size -- is printed under the
 * slider where a judge can watch it change.
 */

const { innocenceBudgetMin, innocenceBudgetMax, innocenceBudgetCurve } = controls

/** Slider position (0-1) for a budget. Inverse of `budgetFromPosition`. */
function positionFromBudget(budget: number): number {
  const span = (budget - innocenceBudgetMin) / (innocenceBudgetMax - innocenceBudgetMin)
  return Math.pow(Math.max(0, Math.min(1, span)), 1 / innocenceBudgetCurve)
}

/** Budget for a slider position, quantised so the tick values are reachable. */
function budgetFromPosition(position: number): number {
  const raw =
    innocenceBudgetMin +
    (innocenceBudgetMax - innocenceBudgetMin) * Math.pow(position, innocenceBudgetCurve)
  return Math.round(raw * 100) / 100
}

/** Resolution of the underlying range input. Fine enough to feel continuous. */
const POSITION_STEPS = 1000

interface Regime {
  budget: number
  name: string
}

/**
 * The three regimes, at the budgets where S1's plan visibly changes shape:
 * step-up verification only, a mixed plan, then full freeze authority.
 */
const REGIMES: Regime[] = [
  { budget: innocenceBudgetMin, name: 'gentle' },
  { budget: controls.innocenceMixed, name: 'mixed' },
  { budget: controls.innocenceFullAuthority, name: 'full authority' },
]

function regimeFor(budget: number): string {
  let name = REGIMES[0]!.name
  for (const regime of REGIMES) {
    if (budget >= regime.budget) name = regime.name
  }
  return name
}

const ACTION_NOUN: Record<FreezeAction, [string, string]> = {
  full_freeze: ['freeze', 'freezes'],
  outbound_hold: ['hold', 'holds'],
  step_up_verification: ['step-up verification', 'step-up verifications'],
}

/**
 * What the plan is *made of*, in one line.
 *
 * The count alone hides the interesting behaviour: 18 and 25 look like more of
 * the same thing until you can see that the 18 are step-up verifications and
 * the 25 are full freezes.
 */
function composition(plan: PlanStep[]): string | null {
  if (!plan.length) return null

  const order: FreezeAction[] = [
    'full_freeze',
    'outbound_hold',
    'step_up_verification',
  ]
  const counts = new Map<FreezeAction, number>()
  for (const step of plan) {
    counts.set(step.action, (counts.get(step.action) ?? 0) + 1)
  }

  const kinds = order.filter((action) => (counts.get(action) ?? 0) > 0)
  const parts = kinds.map((action) => {
    const n = counts.get(action) ?? 0
    const [one, many] = ACTION_NOUN[action]
    // "25 full freezes" when that is the whole plan; plain "13 freezes" when it
    // sits next to something gentler and the contrast is already visible.
    const noun =
      action === 'full_freeze' && kinds.length === 1
        ? `full ${n === 1 ? one : many}`
        : n === 1
          ? one
          : many
    return `${n} ${noun}`
  })

  return parts.join(' + ')
}

interface SliderProps {
  label: string
  hint: string
  value: number
  min: number
  max: number
  step: number
  format: (value: number) => string
  onChange: (value: number) => void
}

function Slider({
  label,
  hint,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: SliderProps) {
  const id = `slider-${label.replace(/\s+/g, '-').toLowerCase()}`
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <label htmlFor={id} className="text-[14px] text-hi">
          {label}
        </label>
        <span className="font-mono text-[14px] text-hi tabular-nums">
          {format(value)}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        title={hint}
        className="w-full accent-[#8A9AAA] h-1 cursor-pointer"
      />
    </div>
  )
}

/** The harm limit, with warped travel, regime ticks and a live composition. */
function HarmLimit({ plan }: { plan: PlanStep[] }) {
  const innocenceBudget = useConsole((s) => s.innocenceBudget)
  const setInnocenceBudget = useConsole((s) => s.setInnocenceBudget)

  const id = 'slider-harm-limit'
  const parts = composition(plan)

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <label htmlFor={id} className="text-[14px] text-hi">
          Harm limit
        </label>
        <span className="font-mono text-[14px] text-hi tabular-nums">
          B = {innocenceBudget.toFixed(2)}
        </span>
      </div>

      <input
        id={id}
        type="range"
        min={0}
        max={POSITION_STEPS}
        step={1}
        value={Math.round(positionFromBudget(innocenceBudget) * POSITION_STEPS)}
        onChange={(event) =>
          setInnocenceBudget(budgetFromPosition(Number(event.target.value) / POSITION_STEPS))
        }
        aria-valuetext={`B = ${innocenceBudget.toFixed(2)}, ${regimeFor(innocenceBudget)}`}
        title="How much risk of freezing innocent people we accept. Lower it and the plan uses gentler actions."
        className="w-full accent-[#8A9AAA] h-1 cursor-pointer"
      />

      {/* Regime ticks. Clicking one snaps to that exact budget, which is how you
          reach 0.25 and 0.50 on stage without hunting for them. */}
      <div className="relative h-4 mt-0.5" aria-hidden>
        {REGIMES.map((regime) => {
          const at = positionFromBudget(regime.budget)
          // Centre the label on its mark, except at the ends of the rail where
          // centring would hang half of it outside the panel.
          const align =
            at <= 0.02
              ? 'items-start translate-x-0'
              : at >= 0.98
                ? 'items-end -translate-x-full'
                : 'items-center -translate-x-1/2'
          return (
            <button
              key={regime.name}
              type="button"
              tabIndex={-1}
              onClick={() => setInnocenceBudget(regime.budget)}
              title={`${regime.budget.toFixed(2)} — ${regime.name}`}
              className={`absolute top-0 flex flex-col group ${align}`}
              style={{ left: `${at * 100}%` }}
            >
              <span className="w-px h-1.5 bg-ink-line group-hover:bg-lo" />
              <span className="font-mono text-[10px] text-lo/70 group-hover:text-lo leading-none mt-0.5 tabular-nums">
                {regime.budget.toFixed(2)}
              </span>
            </button>
          )
        })}
      </div>

      {/* The payoff line: the regime by name, and what the plan is made of.
          It replaced a static hint -- an operator learns far more from seeing
          "13 freezes + 1 hold" become "25 full freezes" than from being told
          that lowering the limit produces gentler actions. */}
      <p className="text-[13px] mt-1 leading-snug">
        <span className="text-lo">{regimeFor(innocenceBudget)}</span>
        {parts ? (
          <>
            <span className="text-lo"> · </span>
            <span className="text-hi">{parts}</span>
          </>
        ) : (
          <span className="text-lo"> · run the case to see the plan</span>
        )}
      </p>
    </div>
  )
}

export default function BudgetControls({ plan }: { plan: PlanStep[] }) {
  const budgetK = useConsole((s) => s.budgetK)
  const adaptive = useConsole((s) => s.adaptiveAdversary)
  const setBudgetK = useConsole((s) => s.setBudgetK)
  const setAdaptive = useConsole((s) => s.setAdaptiveAdversary)

  return (
    <div className="space-y-2.5">
      <Slider
        label="Freezes allowed"
        hint="The most accounts we may freeze for this case."
        value={budgetK}
        min={1}
        max={80}
        step={1}
        format={(v) => `K = ${v}`}
        onChange={setBudgetK}
      />

      <HarmLimit plan={plan} />

      <label className="flex items-start gap-2 cursor-pointer group">
        <input
          type="checkbox"
          checked={adaptive}
          onChange={(event) => setAdaptive(event.target.checked)}
          className="mt-0.5 accent-[#8A9AAA]"
        />
        <span className="leading-tight">
          <span className="text-[14px] text-hi">Fraudster fights back</span>
          <span className="text-[12.5px] text-lo leading-snug block">
            They reroute when we block a path.
          </span>
        </span>
      </label>
    </div>
  )
}
