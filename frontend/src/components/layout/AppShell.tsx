import { NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'

/**
 * Chrome for the whole console: deep, cold, quiet. Hairline rules at 1px,
 * never 2px. No amber, teal or crimson anywhere in here -- those three colours
 * are reserved for money and nothing else.
 */

const TABS = [
  { to: '/', label: 'Live case', end: true },
  { to: '/rings', label: 'Rings' },
  { to: '/evaluation', label: 'Results' },
  { to: '/data', label: 'Data' },
] as const

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { data: health, error } = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 10_000,
  })

  return (
    <div className="h-full flex flex-col bg-ink">
      <header className="shrink-0 flex items-center justify-between h-12 px-5 border-b border-ink-line">
        <div className="flex items-center gap-6">
          <span className="font-display text-[17.5px] tracking-display text-hi">
            chakravyuh
          </span>

          <nav className="flex items-center gap-1" aria-label="Sections">
            {TABS.map((tab) => (
              <NavLink
                key={tab.to}
                to={tab.to}
                end={'end' in tab ? tab.end : false}
                className={({ isActive }) =>
                  [
                    'px-2.5 py-1 rounded-panel text-[15px] transition-colors',
                    isActive ? 'text-hi bg-ink-raised' : 'text-lo hover:text-hi',
                  ].join(' ')
                }
              >
                {tab.label}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-3 font-mono text-[13px] text-lo">
          {health && <span>phase {health.phase}</span>}
          <span aria-hidden>·</span>
          <span>seed {health?.master_seed ?? '—'}</span>
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              error ? 'bg-lo' : 'bg-hi'
            }`}
            aria-label={error ? 'Backend offline' : 'Backend live'}
          />
        </div>
      </header>

      <main className="flex-1 min-h-0">{children}</main>
    </div>
  )
}
