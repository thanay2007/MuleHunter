import type { Scenario } from '@/api/client'
import { duration, rupees, typologyLabel } from '@/lib/format'

interface Props {
  scenarios: Scenario[]
  selectedId: string | null
  onSelect: (id: string) => void
}

/**
 * The six seeded incidents, as a dropdown plus a one-line summary.
 *
 * This used to be six stacked cards. They read well, but they consumed most of
 * the left rail and pushed the ordered freeze plan below the fold on a
 * 1366x768 projector -- and the plan is the product. Picking the case is a
 * five-second act at the start of a four-minute demo, so it gets a control
 * sized like one.
 *
 * Complaint delay survives the compression, because it is the variable that
 * matters most to recovery: the whole product is a bet on the golden hour.
 */
export default function ScenarioPicker({ scenarios, selectedId, onSelect }: Props) {
  const selected = scenarios.find((s) => s.scenario_id === selectedId) ?? null
  const urgent = selected ? selected.complaint_delay_minutes <= 45 : false

  return (
    <div>
      <label className="sr-only" htmlFor="case-select">
        Case
      </label>
      <select
        id="case-select"
        value={selectedId ?? ''}
        onChange={(event) => onSelect(event.target.value)}
        className="w-full bg-ink-raised border border-ink-line rounded-panel px-2 py-1.5 text-[14px] text-hi focus:outline-none focus:border-hi/40 cursor-pointer"
      >
        {scenarios.map((scenario) => (
          <option key={scenario.scenario_id} value={scenario.scenario_id}>
            {scenario.scenario_id} — {scenario.name.split(' — ')[0]} ·{' '}
            {rupees(scenario.amount_inr)}
          </option>
        ))}
      </select>

      {selected && (
        <p className="text-[12.5px] text-lo mt-1 leading-snug truncate">
          {selected.victim_district} · {typologyLabel(selected.ring_typology)} ·{' '}
          <span className={`font-mono ${urgent ? 'text-hi' : 'text-lo'}`}>
            {duration(selected.complaint_delay_minutes)}
          </span>
        </p>
      )}
    </div>
  )
}
