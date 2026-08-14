import { useMemo } from 'react'
import type { PlanStep } from '@/api/client'
import type { ReplayHeader, StreamStatus } from '@/hooks/useReplayStream'
import { elapsed } from '@/lib/format'

/**
 * The incident transport bar.
 *
 * Shows where the replay has reached across the response horizon, when the
 * victim's complaint lands, and the minute each freeze instruction is issued.
 *
 * This is the golden-hour argument as a picture. The complaint marker sits a
 * long way into a window in which the money is already moving, and every teal
 * tick to the right of it is an instruction that could only be issued after
 * someone finally knew. The distance between the start of the bar and that
 * dashed line is the thing the product is trying to buy back.
 *
 * The bar is a readout, not a control: the server owns the clock and streams
 * frames at its own rate, so there is nothing here to scrub. Presenting it as
 * a draggable slider would imply a seek the backend cannot honour.
 */

interface Props {
  header: ReplayHeader | null
  /** Fallback horizon before the stream header arrives. */
  fallbackHorizon: number
  complaintMinute: number
  minute: number
  plan: PlanStep[]
  status: StreamStatus
}

const TICK_MINUTES = 60

export default function IncidentTimeline({
  header,
  fallbackHorizon,
  complaintMinute,
  minute,
  plan,
  status,
}: Props) {
  const horizon = header?.horizon_minutes ?? fallbackHorizon
  const progress = horizon > 0 ? Math.min(1, minute / horizon) : 0
  const complaintAt = horizon > 0 ? Math.min(1, complaintMinute / horizon) : 0

  const ticks = useMemo(() => {
    const out: number[] = []
    for (let m = 0; m <= horizon; m += TICK_MINUTES) out.push(m)
    return out
  }, [horizon])

  // Freeze instructions collapse onto the same minute frequently, so group
  // them: one tick per minute, sized by how many landed there.
  const freezeTicks = useMemo(() => {
    const byMinute = new Map<number, number>()
    for (const step of plan) {
      byMinute.set(step.issue_at_minute, (byMinute.get(step.issue_at_minute) ?? 0) + 1)
    }
    return [...byMinute.entries()]
      .map(([at, n]) => ({ at, n }))
      .sort((a, b) => a.at - b.at)
  }, [plan])

  const idle = status === 'idle'

  return (
    <div className="px-5 py-3">
      <div className="flex items-baseline justify-between mb-2">
        <div className="flex items-baseline gap-3">
          <span className="label-lo">Response window</span>
          {status === 'streaming' && (
            <span className="flex items-center gap-1.5 text-[11px] text-lo">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-hi animate-pulse" />
              replaying
            </span>
          )}
          {status === 'done' && (
            <span className="text-[11px] text-lo">replay complete</span>
          )}
        </div>

        <div className="flex items-baseline gap-2 font-mono text-[12px] tabular-nums">
          <span className={idle ? 'text-lo' : 'text-hi'}>{elapsed(minute)}</span>
          <span className="text-lo">of {elapsed(horizon)}</span>
        </div>
      </div>

      <div className="relative h-9">
        {/* track */}
        <div className="absolute left-0 right-0 top-2.5 h-1 bg-ink-line rounded-full overflow-hidden">
          <div
            className="h-full bg-hi/70 transition-[width] duration-100 ease-linear"
            style={{ width: `${progress * 100}%` }}
          />
        </div>

        {/* the moment anyone found out */}
        <div
          className="absolute top-0 bottom-3 w-px border-l border-dashed border-hi/60"
          style={{ left: `${complaintAt * 100}%` }}
          aria-hidden
        />
        <span
          className="absolute top-0 text-[10px] text-hi/75 whitespace-nowrap pointer-events-none"
          style={{
            left: `${complaintAt * 100}%`,
            transform: complaintAt > 0.75 ? 'translateX(calc(-100% - 5px))' : 'translateX(5px)',
          }}
        >
          complaint filed
        </span>

        {/* freeze instructions */}
        {freezeTicks.map((tick) => {
          const at = horizon > 0 ? Math.min(1, tick.at / horizon) : 0
          const landed = minute >= tick.at
          return (
            <span
              key={tick.at}
              className="absolute top-1.5 w-[3px] rounded-full bg-interdict"
              style={{
                left: `${at * 100}%`,
                height: `${Math.min(11, 4 + tick.n * 1.4)}px`,
                opacity: landed ? 1 : 0.3,
              }}
              title={`${tick.n} freeze ${tick.n === 1 ? 'instruction' : 'instructions'} at ${elapsed(tick.at)}`}
            />
          )
        })}

        {/* playhead */}
        {!idle && (
          <div
            className="absolute top-1 h-4 w-px bg-hi"
            style={{ left: `${progress * 100}%` }}
            aria-hidden
          />
        )}

        {/* hour ticks */}
        {ticks.map((tick) => {
          const at = horizon > 0 ? tick / horizon : 0
          return (
            <span
              key={tick}
              className="absolute bottom-0 font-mono text-[10px] text-lo/70 -translate-x-1/2 pointer-events-none"
              style={{ left: `${at * 100}%` }}
            >
              {tick === 0 ? '0' : `${tick / 60}h`}
            </span>
          )
        })}
      </div>

      {freezeTicks.length > 0 && (
        <p className="text-[11px] text-lo mt-1.5">
          <span className="inline-block w-[3px] h-2.5 rounded-full bg-interdict align-middle mr-1.5" />
          {freezeTicks.reduce((sum, t) => sum + t.n, 0)} freeze instructions, the first
          at {elapsed(freezeTicks[0]!.at)}
          {complaintMinute > 0 && (
            <> — {elapsed(complaintMinute)} of the window was already gone before
            anyone reported it</>
          )}
        </p>
      )}
    </div>
  )
}
