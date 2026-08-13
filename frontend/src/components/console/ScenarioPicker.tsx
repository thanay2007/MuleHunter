import type { Scenario } from '@/api/client'
import { duration, rupees, typologyLabel } from '@/lib/format'

interface Props {
  scenarios: Scenario[]
  selectedId: string | null
  onSelect: (id: string) => void
}

/**
 * The six seeded incidents. Complaint delay is surfaced on every card because
 * it is the variable that matters most to recovery -- the whole product is a
 * bet on the golden hour.
 */
export default function ScenarioPicker({ scenarios, selectedId, onSelect }: Props) {
  return (
    <div className="flex flex-col gap-1.5">
      {scenarios.map((scenario) => {
        const active = scenario.scenario_id === selectedId
        const urgent = scenario.complaint_delay_minutes <= 45

        return (
          <button
            key={scenario.scenario_id}
            type="button"
            onClick={() => onSelect(scenario.scenario_id)}
            aria-pressed={active}
            className={[
              'w-full text-left px-3 py-2.5 rounded-panel border transition-colors',
              active
                ? 'bg-ink-raised border-hi/40'
                : 'bg-transparent border-ink-line hover:border-lo/50',
            ].join(' ')}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-mono text-[11px] text-lo">{scenario.scenario_id}</span>
              <span className="font-mono text-[12px] text-hi">
                {rupees(scenario.amount_inr)}
              </span>
            </div>

            <div className="text-[12.5px] text-hi leading-snug mt-0.5">
              {scenario.name.split(' — ')[0]}
            </div>

            <div className="text-[11px] text-lo mt-1 flex items-center gap-1.5 flex-wrap">
              <span>{scenario.victim_district}</span>
              <span aria-hidden>·</span>
              <span>{typologyLabel(scenario.ring_typology)}</span>
            </div>

            <div className="mt-1.5 flex items-center gap-1.5 text-[11px]">
              <span className="text-lo">reported after</span>
              <span className={`font-mono ${urgent ? 'text-hi' : 'text-lo'}`}>
                {duration(scenario.complaint_delay_minutes)}
              </span>
            </div>
          </button>
        )
      })}
    </div>
  )
}
