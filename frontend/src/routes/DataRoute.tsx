import { useQuery } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '@/api/client'
import { archetypeLabel, count, percent } from '@/lib/format'
import { tokens } from '@/theme/tokens'

/**
 * Dataset transparency. This is the answer to "is your data real?" -- it is
 * not, and this page shows exactly what it is instead.
 */

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="panel px-4 py-3">
      <div className="font-mono text-[22px] text-hi leading-none">{value}</div>
      <div className="text-[13px] text-lo mt-1.5">{label}</div>
    </div>
  )
}

const chartAxis = {
  stroke: tokens.inkLine,
  tick: { fill: tokens.textLo, fontSize: 13, fontFamily: 'IBM Plex Mono' },
}

export default function DataRoute() {
  const { data, isPending, error } = useQuery({
    queryKey: ['dataset-summary'],
    queryFn: api.datasetSummary,
  })

  if (isPending) return <p className="p-8 text-[15.5px] text-lo">Loading dataset…</p>
  if (error) return <p className="p-8 text-[15.5px] text-lo">{(error as Error).message}</p>

  const hourly = data.hourly.map((h) => ({
    hour: String(h.hour).padStart(2, '0'),
    count: h.count,
  }))
  const archetypes = data.archetypes.map((a) => ({
    name: archetypeLabel(a.name),
    count: a.count,
    isHardNegative: a.name === 'legit_high_velocity',
  }))

  return (
    <div className="h-full overflow-y-auto p-5">
      <header className="mb-5">
        <h1 className="font-display text-lg text-hi tracking-display">
          All this data is made up
        </h1>
        <p className="text-[15.5px] text-lo mt-1 max-w-3xl leading-relaxed">
          No real bank data, no real PII, no real account numbers. The generator is
          calibrated to publicly reported I4C and RBI figures on layering depth, cash-out
          timing and mule prevalence, and every distribution choice is documented in{' '}
          <span className="font-mono text-hi">app/simulator/README.md</span>. Regenerating
          from the same seed reproduces these files byte for byte.
        </p>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-6">
        <Stat value={count(data.accounts)} label="Everyday accounts" />
        <Stat value={count(data.transactions)} label="Transactions" />
        <Stat value={count(data.mule_accounts)} label="Mule accounts" />
        <Stat value={percent(data.mule_prevalence, 2)} label="Share that are mules" />
        <Stat value={String(data.banks)} label="Banks" />
        <Stat value={String(data.districts)} label="Districts" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <section className="panel p-4">
          <h2 className="font-display text-[16.5px] text-hi tracking-display mb-1">
            When people pay, by hour
          </h2>
          <p className="text-[13.5px] text-lo mb-3">
            Peaks near 11:00 and 20:00 IST, matching the reported intraday UPI shape.
          </p>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={hourly} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
                <CartesianGrid stroke={tokens.inkLine} vertical={false} />
                <XAxis dataKey="hour" {...chartAxis} interval={2} />
                <YAxis {...chartAxis} tickFormatter={(v: number) => `${v / 1000}k`} />
                <Tooltip
                  cursor={{ fill: tokens.inkRaised }}
                  contentStyle={{
                    background: tokens.inkRaised,
                    border: `1px solid ${tokens.inkLine}`,
                    borderRadius: 3,
                    fontSize: 14,
                    fontFamily: 'IBM Plex Mono',
                    color: tokens.textHi,
                  }}
                  formatter={(value: number) => [count(value), 'transactions']}
                />
                <Bar dataKey="count" fill={tokens.textLo} radius={[1, 1, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="panel p-4">
          <h2 className="font-display text-[16.5px] text-hi tracking-display mb-1">
            Kinds of account
          </h2>
          <p className="text-[13.5px] text-lo mb-3">
            The highlighted bar is the hard-negative class: legitimate high-velocity
            accounts that behave almost exactly like layering mules.
          </p>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={archetypes}
                layout="vertical"
                margin={{ top: 4, right: 12, bottom: 0, left: 96 }}
              >
                <CartesianGrid stroke={tokens.inkLine} horizontal={false} />
                <XAxis type="number" {...chartAxis} />
                <YAxis type="category" dataKey="name" width={150} {...chartAxis} />
                <Tooltip
                  cursor={{ fill: tokens.inkRaised }}
                  contentStyle={{
                    background: tokens.inkRaised,
                    border: `1px solid ${tokens.inkLine}`,
                    borderRadius: 3,
                    fontSize: 14,
                    fontFamily: 'IBM Plex Mono',
                    color: tokens.textHi,
                  }}
                  formatter={(value: number) => [count(value), 'accounts']}
                />
                <Bar dataKey="count" radius={[0, 1, 1, 0]}>
                  {archetypes.map((entry) => (
                    <Cell
                      key={entry.name}
                      fill={entry.isHardNegative ? tokens.textHi : tokens.textLo}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>

      <section className="panel p-4 mt-3">
        <h2 className="font-display text-[16.5px] text-hi tracking-display mb-3">
          How money moves
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {data.channels.map((channel) => (
            <div key={channel.name}>
              <div className="font-mono text-[17.5px] text-hi">
                {percent(channel.count / data.transactions)}
              </div>
              <div className="text-[13px] text-lo mt-0.5">{channel.name}</div>
              <div className="h-1 bg-ink-line mt-1.5 rounded-full overflow-hidden">
                <div
                  className="h-full bg-lo"
                  style={{ width: `${(channel.count / data.transactions) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
        <p className="text-[13.5px] text-lo mt-3 leading-relaxed">
          ATM withdrawal is 6% of ordinary traffic by design. If only mules used ATMs,
          cash-out proximity would trivially solve detection and every benchmark number
          afterwards would be worthless.
        </p>
      </section>
    </div>
  )
}
