import { useConsole } from '@/store/console'

/**
 * The two budgets the operator actually controls.
 *
 * These are not settings, they are the policy question. K is how much freeze
 * authority is available; B is how much collateral harm is acceptable to spend
 * it. Moving B is the answer to "what if your classifier is wrong" -- tighten
 * it and the solver switches from full freezes to outbound holds and step-up
 * verification rather than simply freezing fewer accounts.
 */

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
        className="w-full accent-[#8A9AAA] h-1 cursor-pointer"
      />
      <p className="text-[13px] text-lo mt-1 leading-snug">{hint}</p>
    </div>
  )
}

export default function BudgetControls() {
  const budgetK = useConsole((s) => s.budgetK)
  const innocenceBudget = useConsole((s) => s.innocenceBudget)
  const adaptive = useConsole((s) => s.adaptiveAdversary)
  const setBudgetK = useConsole((s) => s.setBudgetK)
  const setInnocenceBudget = useConsole((s) => s.setInnocenceBudget)
  const setAdaptive = useConsole((s) => s.setAdaptiveAdversary)

  return (
    <div className="space-y-4">
      <Slider
        label="Freeze authority"
        hint="How many freeze instructions may be issued for this incident."
        value={budgetK}
        min={1}
        max={80}
        step={1}
        format={(v) => `K = ${v}`}
        onChange={setBudgetK}
      />
      <Slider
        label="Innocence budget"
        hint="Total priced harm the plan may spend. Tighten it and the solver switches to gentler actions."
        value={innocenceBudget}
        min={0.05}
        max={8}
        step={0.05}
        format={(v) => `B = ${v.toFixed(2)}`}
        onChange={setInnocenceBudget}
      />

      <label className="flex items-start gap-2 cursor-pointer group">
        <input
          type="checkbox"
          checked={adaptive}
          onChange={(event) => setAdaptive(event.target.checked)}
          className="mt-0.5 accent-[#8A9AAA]"
        />
        <span>
          <span className="text-[14px] text-hi block leading-tight">
            Adaptive adversary
          </span>
          <span className="text-[13px] text-lo leading-snug block mt-0.5">
            Assume the operator reroutes blocked money instead of giving up.
          </span>
        </span>
      </label>
    </div>
  )
}
