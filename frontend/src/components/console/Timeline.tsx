import { useMemo } from 'react'
import { Pause, Play, RotateCcw } from 'lucide-react'
import type { IncidentGraph } from '@/api/client'
import { flowSeries } from '@/lib/incident'
import { elapsed } from '@/lib/format'
import { SPEEDS, type Replay } from '@/hooks/useReplay'
import { tokens } from '@/theme/tokens'

/**
 * The incident timeline: a histogram of fraud flow per minute, with the
 * complaint marked on it.
 *
 * This chart is the golden-hour argument in one picture. The money has almost
 * always finished leaving before the complaint marker is reached, and the gap
 * between those two positions is the entire opportunity the product is going
 * after.
 */

interface Props {
  graph: IncidentGraph
  replay: Replay
  complaintMinute: number
}

const HEIGHT = 74
const BUCKETS = 140

export default function Timeline({ graph, replay, complaintMinute }: Props) {
  const horizon = graph.horizon_minutes
  const series = useMemo(() => flowSeries(graph, BUCKETS), [graph])

  const peak = useMemo(
    () => Math.max(1, ...series.map((b) => b.internal + b.exit)),
    [series],
  )

  const progress = Math.min(1, replay.minute / horizon)
  const complaintX = Math.min(1, complaintMinute / horizon)
  const barWidth = 100 / BUCKETS

  return (
    <div className="px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={replay.toggle}
            aria-label={replay.playing ? 'Pause replay' : 'Play replay'}
            className="w-7 h-7 flex items-center justify-center rounded-panel border border-ink-line text-hi hover:bg-ink-raised transition-colors"
          >
            {replay.playing ? (
              <Pause size={13} strokeWidth={2} />
            ) : (
              <Play size={13} strokeWidth={2} />
            )}
          </button>

          <button
            type="button"
            onClick={replay.restart}
            aria-label="Restart replay"
            className="w-7 h-7 flex items-center justify-center rounded-panel border border-ink-line text-lo hover:text-hi hover:bg-ink-raised transition-colors"
          >
            <RotateCcw size={13} strokeWidth={2} />
          </button>

          <div className="flex items-center gap-0.5 ml-1" role="group" aria-label="Playback speed">
            {SPEEDS.map((speed) => (
              <button
                key={speed}
                type="button"
                onClick={() => replay.setSpeed(speed)}
                aria-pressed={replay.speed === speed}
                className={[
                  'font-mono text-[11px] px-1.5 py-0.5 rounded-panel transition-colors',
                  replay.speed === speed
                    ? 'text-hi bg-ink-raised'
                    : 'text-lo hover:text-hi',
                ].join(' ')}
              >
                {speed}×
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-4 font-mono text-[12px]">
          <span className="text-hi">{elapsed(replay.minute)}</span>
          <span className="text-lo">of {elapsed(horizon)}</span>
        </div>
      </div>

      <div className="relative" style={{ height: HEIGHT }}>
        <svg
          width="100%"
          height={HEIGHT}
          viewBox={`0 0 100 ${HEIGHT}`}
          preserveAspectRatio="none"
          aria-hidden
        >
          {/* baseline */}
          <line
            x1="0"
            y1={HEIGHT - 0.5}
            x2="100"
            y2={HEIGHT - 0.5}
            stroke={tokens.inkLine}
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />

          {series.map((bucket, index) => {
            const total = bucket.internal + bucket.exit
            if (total <= 0) return null

            const played = bucket.minute <= replay.minute
            const scale = (HEIGHT - 6) / peak
            const exitHeight = bucket.exit * scale
            const internalHeight = bucket.internal * scale
            const x = index * barWidth

            return (
              <g key={bucket.minute} opacity={played ? 1 : 0.22}>
                {internalHeight > 0 && (
                  <rect
                    x={x}
                    y={HEIGHT - internalHeight - exitHeight}
                    width={barWidth * 0.86}
                    height={internalHeight}
                    fill={tokens.flow}
                  />
                )}
                {exitHeight > 0 && (
                  <rect
                    x={x}
                    y={HEIGHT - exitHeight}
                    width={barWidth * 0.86}
                    height={exitHeight}
                    fill={tokens.burn}
                  />
                )}
              </g>
            )
          })}

          {/* complaint marker */}
          <line
            x1={complaintX * 100}
            y1="0"
            x2={complaintX * 100}
            y2={HEIGHT}
            stroke={tokens.textHi}
            strokeWidth="1"
            strokeDasharray="3 3"
            vectorEffect="non-scaling-stroke"
          />

          {/* playhead */}
          <line
            x1={progress * 100}
            y1="0"
            x2={progress * 100}
            y2={HEIGHT}
            stroke={tokens.textHi}
            strokeWidth="1.5"
            vectorEffect="non-scaling-stroke"
          />
        </svg>

        <span
          className="absolute top-0 font-mono text-[10px] text-hi/80 pointer-events-none whitespace-nowrap"
          style={{
            left: `${complaintX * 100}%`,
            transform:
              complaintX > 0.7 ? 'translateX(calc(-100% - 6px))' : 'translateX(6px)',
          }}
        >
          complaint filed
        </span>

        {/* The range input is the real control: draggable and keyboard-operable. */}
        <input
          type="range"
          min={0}
          max={horizon}
          step={1}
          value={Math.round(replay.minute)}
          onChange={(event) => replay.scrub(Number(event.target.value))}
          aria-label="Scrub incident timeline"
          aria-valuetext={elapsed(replay.minute)}
          className="absolute inset-0 w-full h-full opacity-0 cursor-ew-resize"
        />
      </div>

      <div className="flex items-center justify-between mt-1.5">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5 text-[11px] text-lo">
            <span
              className="inline-block w-2 h-2"
              style={{ backgroundColor: tokens.flow }}
              aria-hidden
            />
            moving between accounts
          </span>
          <span className="flex items-center gap-1.5 text-[11px] text-lo">
            <span
              className="inline-block w-2 h-2"
              style={{ backgroundColor: tokens.burn }}
              aria-hidden
            />
            leaving the banking system
          </span>
        </div>
        <span className="font-mono text-[10px] text-lo">{elapsed(horizon)} horizon</span>
      </div>
    </div>
  )
}
