import { NavLink, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import Breadcrumb from '@/components/portal/Breadcrumb'
import ClassificationStrip from '@/components/portal/ClassificationStrip'
import Masthead from '@/components/portal/Masthead'
import PortalFooter from '@/components/portal/PortalFooter'
import { useChrome } from '@/i18n/useChrome'
import { useConsole } from '@/store/console'

/**
 * The portal frame, and inside it the operations canvas.
 *
 *     Masthead              64px   which desk, who is at it, what time it is
 *     ClassificationStrip   22px   RESTRICTED / SYNTHETIC / PROTOTYPE
 *     nav                   48px   (pre-existing, restyled to the navy ground)
 *     Breadcrumb            22px   where you are
 *     <main>                       untouched dark canvas
 *     PortalFooter          32px   disclaimer, build, audit id
 *
 * Added chrome is 64 + 22 + 22 + 32 = 140px, which is the budget. The canvas is
 * still the star: this is a frame around it, not a replacement for it, and
 * nothing in the frame is allowed to restyle what is inside it.
 *
 * COLOUR: navy, steel, white, grey. No saffron -- it sits next to `flow` amber
 * and would wreck the money colour language. No amber, teal or crimson either.
 */

const TABS = [
  { to: '/', key: 'navActiveIncident', end: true },
  { to: '/rings', key: 'navNetworkAnalysis' },
  { to: '/evaluation', key: 'navBenchmark' },
  { to: '/data', key: 'navProvenance' },
  { to: '/orders', key: 'navOrders' },
  { to: '/audit', key: 'navAudit' },
] as const

export default function AppShell({ children }: { children: React.ReactNode }) {
  const t = useChrome()
  const location = useLocation()
  const scenarioId = useConsole((s) => s.scenarioId)

  const { data: health, error } = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 10_000,
  })

  const { data: scenarios } = useQuery({
    queryKey: ['scenarios'],
    queryFn: api.scenarios,
  })
  const scenario = scenarios?.find((s) => s.scenario_id === scenarioId) ?? null

  // The trail names the real case rather than the route, so the crumb a judge
  // reads matches the case number on the docket below it.
  const tail: Record<string, string> = {
    '/': t.crumbPlan,
    '/rings': t.navNetworkAnalysis,
    '/evaluation': t.navBenchmark,
    '/data': t.navProvenance,
    '/orders': t.navOrders,
    '/audit': t.navAudit,
  }
  const trail = [t.crumbHome, t.crumbIncidents]
  if (scenario) trail.push(scenario.case_id)
  trail.push(tail[location.pathname] ?? t.crumbPlan)

  return (
    <div className="h-full flex flex-col bg-ink">
      <Masthead />
      <ClassificationStrip />

      <header className="shrink-0 flex items-center justify-between h-12 px-5 bg-institution-navy border-b border-institution-rule">
        <div className="flex items-center gap-6 min-w-0">
          <span className="font-display text-[17.5px] tracking-display text-institution-on shrink-0">
            chakravyuh
          </span>

          <nav className="flex items-center gap-1 min-w-0" aria-label="Sections">
            {TABS.map((tab) => (
              <NavLink
                key={tab.to}
                to={tab.to}
                end={'end' in tab ? tab.end : false}
                className={({ isActive }) =>
                  [
                    'px-2.5 py-1 rounded-panel text-[14px] whitespace-nowrap transition-colors',
                    isActive
                      ? 'text-institution-on bg-institution-deep'
                      : 'text-institution-lo hover:text-institution-on',
                  ].join(' ')
                }
              >
                {t[tab.key]}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-3 font-mono text-[13px] text-institution-lo shrink-0">
          {health && <span className="hidden xl:inline">phase {health.phase}</span>}
          <span className="hidden xl:inline" aria-hidden>
            ·
          </span>
          <span className="hidden lg:inline">seed {health?.master_seed ?? '—'}</span>
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              error ? 'bg-institution-steel' : 'bg-institution-on'
            }`}
            aria-label={error ? 'Backend offline' : 'Backend live'}
          />
        </div>
      </header>

      <Breadcrumb trail={trail} />

      <main className="flex-1 min-h-0">{children}</main>

      <PortalFooter />
    </div>
  )
}
