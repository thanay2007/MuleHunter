import { useMemo } from 'react'
import type { PlanStep } from '@/api/client'
import type { ReplayHeader, StreamStatus } from '@/hooks/useReplayStream'
import { duration, elapsed } from '@/lib/format'

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
 *
 * LAYOUT. Everything here is absolutely positioned along a shared axis, so the
 * vertical bands are laid out explicitly and never overlap: labels on top, the
 * track through the middle, hour marks underneath. An earlier version put the
 * complaint label at the same offset as the track and it printed straight
 * through the bar.
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

/** Vertical bands, in px from the top of the axis box. */
const BAND = {
  height: 54,
  label: 0,
  stem: 17,
  stemHeight: 18,
  track: 23,
  trackHeight: 6,
  tickTop: 19,
  hours: 39,
} as const

/**
 * Keep a label inside the axis instead of letting it hang off either end.
 * At the extremes it anchors to the edge; everywhere else it centres.
 */
function anchor(fraction: number): string {
  if (fraction <= 0.02) return 'translateX(0)'
  if (fraction >= 0.98) return 'translateX(-100%)'
  return 'translateX(-50%)'
}

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

  // Freeze instructions land on the same minute frequently, so group them:
  // one tick per minute, sized by how many arrived there.
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
  const totalFreezes = freezeTicks.reduce((sum, t) => sum + t.n, 0)

  return (
    <div className="px-5 py-3">
      <div className="flex items-baseline justify-between gap-4 mb-2">
        <div className="flex items-baseline gap-3">
          <span className="label-lo">Response window</span>
          {status === 'streaming' && (
            <span className="flex items-center gap-1.5 text-[13px] text-lo">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-hi animate-pulse" />
              replaying
            </span>
          )}
          {status === 'done' && (
            <span className="text-[13px] text-lo">replay complete</span>
          )}
        </div>

        <div className="flex items-baseline gap-2 font-mono text-[14px] tabular-nums">
          <span className={idle ? 'text-lo' : 'text-hi'}>{elapsed(minute)}</span>
          <span className="text-lo">of {elapsed(horizon)}</span>
        </div>
      </div>

      <div className="relative" style={{ height: BAND.height }}>
        {/* track */}
        <div
          className="absolute left-0 right-0 bg-ink-line rounded-full overflow-hidden"
          style={{ top: BAND.track, height: BAND.trackHeight }}
        >
          <div
            className="h-full bg-hi/70 transition-[width] duration-100 ease-linear"
            style={{ width: `${progress * 100}%` }}
          />
        </div>

        {/* the moment anyone found out */}
        <div
          className="absolute w-px border-l border-dashed border-hi/60"
          style={{
            left: `${complaintAt * 100}%`,
            top: BAND.stem,
            height: BAND.stemHeight,
          }}
          aria-hidden
        />
        <span
          className="absolute text-[12px] text-hi/80 whitespace-nowrap pointer-events-none"
          style={{
            left: `${complaintAt * 100}%`,
            top: BAND.label,
            transform: anchor(complaintAt),
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
              className="absolute w-[3px] rounded-full bg-interdict"
              style={{
                left: `${at * 100}%`,
                top: BAND.tickTop,
                height: Math.min(14, 6 + tick.n * 1.4),
                opacity: landed ? 1 : 0.3,
              }}
              title={`${tick.n} freeze ${
                tick.n === 1 ? 'instruction' : 'instructions'
              } at ${elapsed(tick.at)}`}
            />
          )
        })}

        {/* playhead */}
        {!idle && (
          <div
            className="absolute w-px bg-hi"
            style={{ left: `${progress * 100}%`, top: BAND.tickTop - 3, height: 20 }}
            aria-hidden
          />
        )}

        {/* hour marks */}
        {ticks.map((tick) => {
          const at = horizon > 0 ? tick / horizon : 0
          return (
            <span
              key={tick}
              className="absolute font-mono text-[12px] text-lo/70 pointer-events-none"
              style={{
                left: `${at * 100}%`,
                top: BAND.hours,
                transform: anchor(at),
              }}
            >
              {tick === 0 ? '0' : `${tick / 60}h`}
            </span>
          )
        })}
      </div>

      {totalFreezes > 0 && (
        <p className="text-[13px] text-lo mt-1 leading-relaxed">
          <span className="inline-block w-[3px] h-2.5 rounded-full bg-interdict align-middle mr-1.5" />
          {totalFreezes} freeze {totalFreezes === 1 ? 'instruction' : 'instructions'},
          the first at {elapsed(freezeTicks[0]!.at)}
          {complaintMinute > 0 && (
            <> — nothing could be issued for the first {duration(complaintMinute)},
            because nobody had reported it yet</>
          )}
        </p>
      )}
    </div>
  )
}
