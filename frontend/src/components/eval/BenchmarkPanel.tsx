import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Benchmark, PolicySummary } from '@/api/client'
import { count, percent, rupees, rupeesCompact } from '@/lib/format'
import { tokens } from '@/theme/tokens'

/**
 * The benchmark, rendered straight from `data/benchmark.json`.
 *
 * Nothing here is typed by hand. If the harness has not been run, the route
 * says which command produces the file rather than showing a plausible number.
 */

const AXIS = { stroke: tokens.textLo, fontSize: 13, fontFamily: 'IBM Plex Mono' }

function chartTooltip() {
  return {
    contentStyle: {
      background: tokens.inkRaised,
      border: `1px solid ${tokens.inkLine}`,
      borderRadius: 3,
      fontSize: 13,
      fontFamily: 'IBM Plex Mono',
      color: tokens.textHi,
    },
    labelStyle: { color: tokens.textLo },
  }
}

export function PolicyTable({
  policies,
  labels,
}: {
  policies: PolicySummary[]
  labels: Record<string, string>
}) {
  const best = Math.max(...policies.map((p) => p.recovery_rate_mean), 1e-9)

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[14px] border-collapse min-w-[820px]">
        <thead>
          <tr className="text-lo text-left">
            <th className="font-normal py-2 pr-4">Policy</th>
            <th className="font-normal py-2 px-3 text-right">Recovery</th>
            <th className="font-normal py-2 px-3 text-right">Median</th>
            <th className="font-normal py-2 px-3 text-right">Kept in system</th>
            <th className="font-normal py-2 px-3 text-right">Lost</th>
            <th className="font-normal py-2 px-3 text-right">Innocent frozen</th>
            <th className="font-normal py-2 px-3 text-right">Frozen / incident</th>
            <th className="font-normal py-2 pl-3 text-right">p95 solve</th>
          </tr>
        </thead>
        <tbody>
          {policies.map((p) => {
            const ours = p.policy === 'chakravyuh_greedy'
            return (
              <tr
                key={p.policy}
                className={`border-t border-ink-line ${ours ? 'bg-ink-raised' : ''}`}
              >
                <td className={`py-2.5 pr-4 ${ours ? 'text-hi' : 'text-lo'}`}>
                  {labels[p.policy] ?? p.policy}
                </td>
                <td className="py-2.5 px-3 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <div className="w-16 h-1 bg-ink rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${(p.recovery_rate_mean / best) * 100}%`,
                          backgroundColor: ours ? tokens.interdict : tokens.textLo,
                        }}
                      />
                    </div>
                    <span
                      className={`font-mono tabular-nums ${ours ? 'text-interdict' : 'text-hi'}`}
                    >
                      {percent(p.recovery_rate_mean)}
                    </span>
                  </div>
                </td>
                <td className="py-2.5 px-3 text-right font-mono text-lo tabular-nums">
                  {percent(p.recovery_rate_median)}
                </td>
                <td className="py-2.5 px-3 text-right font-mono text-hi tabular-nums">
                  {rupeesCompact(p.prevented_inr_total)}
                </td>
                <td className="py-2.5 px-3 text-right font-mono text-burn tabular-nums">
                  {rupeesCompact(p.leaked_inr_total)}
                </td>
                <td className="py-2.5 px-3 text-right font-mono tabular-nums">
                  <span className={p.innocent_frozen_total > 0 ? 'text-burn' : 'text-hi'}>
                    {count(p.innocent_frozen_total)}
                  </span>
                  <span className="text-lo">
                    {' '}
                    ({percent(p.innocent_frozen_rate, 1)})
                  </span>
                </td>
                <td className="py-2.5 px-3 text-right font-mono text-lo tabular-nums">
                  {p.frozen_accounts_mean.toFixed(1)}
                </td>
                <td className="py-2.5 pl-3 text-right font-mono text-lo tabular-nums">
                  {p.solve_ms_p95.toFixed(0)} ms
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function DelayCurve({ data }: { data: Benchmark['recovery_vs_delay'] }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
        <CartesianGrid stroke={tokens.inkLine} vertical={false} />
        <XAxis
          dataKey="delay_minutes"
          {...AXIS}
          tickLine={false}
          axisLine={{ stroke: tokens.inkLine }}
          label={{
            value: 'minutes before the victim reports',
            position: 'insideBottom',
            offset: -2,
            fill: tokens.textLo,
            fontSize: 12,
          }}
        />
        <YAxis
          {...AXIS}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
        />
        <Tooltip
          {...chartTooltip()}
          formatter={(value: number) => percent(value)}
          labelFormatter={(v: number) => `reported after ${v} min`}
        />
        <Line
          type="monotone"
          dataKey="chakravyuh_greedy"
          name="Chakravyuh"
          stroke={tokens.interdict}
          strokeWidth={2}
          dot={{ r: 2.5, fill: tokens.interdict }}
        />
        <Line
          type="monotone"
          dataKey="named_account_only"
          name="Current practice"
          stroke={tokens.textLo}
          strokeWidth={1.5}
          strokeDasharray="3 3"
          dot={{ r: 2, fill: tokens.textLo }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

export function InnocenceCurve({ data }: { data: Benchmark['innocence_sweep'] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
        <CartesianGrid stroke={tokens.inkLine} vertical={false} />
        <XAxis
          dataKey="innocence_budget"
          {...AXIS}
          tickLine={false}
          axisLine={{ stroke: tokens.inkLine }}
          label={{
            value: 'innocence budget B',
            position: 'insideBottom',
            offset: -2,
            fill: tokens.textLo,
            fontSize: 12,
          }}
        />
        <YAxis
          {...AXIS}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
        />
        <Tooltip
          {...chartTooltip()}
          formatter={(value: number) => percent(value)}
          labelFormatter={(v: number) => `B = ${v}`}
        />
        <Line
          type="monotone"
          dataKey="recovery_rate"
          name="Recovery"
          stroke={tokens.interdict}
          strokeWidth={2}
          dot={{ r: 2.5, fill: tokens.interdict }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

export function RecoveryHistogram({ policy }: { policy: PolicySummary }) {
  const data = policy.histogram.map((n, i) => ({
    bucket: `${i * 10}-${i * 10 + 10}%`,
    incidents: n,
    mid: i * 10 + 5,
  }))

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -12 }}>
        <CartesianGrid stroke={tokens.inkLine} vertical={false} />
        <XAxis
          dataKey="bucket"
          {...AXIS}
          tickLine={false}
          axisLine={{ stroke: tokens.inkLine }}
          interval={1}
        />
        <YAxis {...AXIS} tickLine={false} axisLine={false} />
        <Tooltip
          {...chartTooltip()}
          formatter={(value: number) => `${value} incidents`}
        />
        <Bar dataKey="incidents" radius={[2, 2, 0, 0]}>
          {data.map((entry) => (
            <Cell
              key={entry.bucket}
              // Opacity carries the magnitude; the colour stays semantic.
              fill={tokens.interdict}
              fillOpacity={0.35 + (entry.mid / 100) * 0.6}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function StatTile({
  label,
  value,
  hint,
  tone = 'plain',
}: {
  label: string
  value: string
  hint?: string
  tone?: 'plain' | 'saved' | 'lost'
}) {
  const colour =
    tone === 'saved' ? 'text-interdict' : tone === 'lost' ? 'text-burn' : 'text-hi'
  return (
    <div className="panel px-4 py-3">
      <div className={`font-mono tabular-nums text-[22px] leading-none ${colour}`}>
        {value}
      </div>
      <div className="text-[13px] text-lo mt-1.5 leading-tight">{label}</div>
      {hint && <div className="text-[12.5px] text-lo/70 mt-1">{hint}</div>}
    </div>
  )
}

export function formatMoney(value: number): string {
  return rupees(value)
}
