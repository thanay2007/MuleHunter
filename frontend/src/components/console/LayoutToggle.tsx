import { Columns2, Maximize2, Rows2 } from 'lucide-react'
import { useConsole, type ConsoleLayout } from '@/store/console'

/**
 * Chooses how the console splits its space between the network and the money.
 *
 * While an incident replays you want the graph as large as it goes; when it
 * finishes you want the two columns of figures. Those are different screens,
 * so this is a control rather than a fixed decision.
 */

const OPTIONS: ReadonlyArray<{
  id: ConsoleLayout
  label: string
  hint: string
  Icon: typeof Rows2
}> = [
  {
    id: 'stacked',
    label: 'Stacked',
    hint: 'Ledger across the bottom',
    Icon: Rows2,
  },
  {
    id: 'side',
    label: 'Side by side',
    hint: 'Ledger docked to the right',
    Icon: Columns2,
  },
  {
    id: 'focus',
    label: 'Focus',
    hint: 'Collapse the ledger, maximise the graph',
    Icon: Maximize2,
  },
]

export default function LayoutToggle() {
  const layout = useConsole((s) => s.layout)
  const setLayout = useConsole((s) => s.setLayout)

  return (
    <div
      className="flex items-center gap-0.5 border border-ink-line rounded-panel p-0.5"
      role="group"
      aria-label="Console layout"
    >
      {OPTIONS.map(({ id, label, hint, Icon }) => {
        const active = layout === id
        return (
          <button
            key={id}
            type="button"
            onClick={() => setLayout(id)}
            aria-pressed={active}
            title={`${label} — ${hint}`}
            className={[
              'w-7 h-6 flex items-center justify-center rounded-[2px] transition-colors',
              active ? 'bg-ink-raised text-hi' : 'text-lo hover:text-hi',
            ].join(' ')}
          >
            <Icon size={14} strokeWidth={2} aria-hidden />
            <span className="sr-only">{label}</span>
          </button>
        )
      })}
    </div>
  )
}
