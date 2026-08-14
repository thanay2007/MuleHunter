import { useEffect, useState } from 'react'
import { tokens } from '@/theme/tokens'

/**
 * The frontier sweep.
 *
 * A single 1px teal line crosses the canvas left to right over 900ms when the
 * plan is issued. Accounts it passes that are in the freeze set snap to a teal
 * ring with a short scale pulse (drawn on the canvas itself, in FlowCanvas).
 *
 * This is the signature moment of the product and it earns its cost: it is the
 * one instant where the whole idea is legible without narration -- the money
 * is running right, and something arrives ahead of it and closes the door.
 *
 * Under `prefers-reduced-motion` the sweep does not run at all; the freeze
 * state simply appears. The information is identical either way.
 */

const SWEEP_MS = 900

interface Props {
  /** Bump this to trigger a sweep. */
  trigger: number
  active: boolean
}

export default function FreezeFrontier({ trigger, active }: Props) {
  const [progress, setProgress] = useState<number | null>(null)

  useEffect(() => {
    if (!active || trigger === 0) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    let frame = 0
    const start = performance.now()

    const step = (now: number) => {
      const t = Math.min(1, (now - start) / SWEEP_MS)
      setProgress(t)
      if (t < 1) {
        frame = requestAnimationFrame(step)
      } else {
        setProgress(null)
      }
    }

    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [trigger, active])

  if (progress === null) return null

  // Eased so the line decelerates into the right edge rather than stopping dead.
  const eased = 1 - (1 - progress) ** 2

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden>
      <div
        className="absolute top-0 bottom-0 w-px"
        style={{
          left: `${eased * 100}%`,
          backgroundColor: tokens.interdict,
          boxShadow: `0 0 12px 1px ${tokens.interdict}`,
          opacity: 0.9 * (1 - progress * 0.35),
        }}
      />
      {/* A short trailing wash, so the line reads as sweeping rather than sliding. */}
      <div
        className="absolute top-0 bottom-0"
        style={{
          left: `${Math.max(0, eased * 100 - 9)}%`,
          width: '9%',
          background: `linear-gradient(90deg, transparent, ${tokens.interdict}22)`,
          opacity: 1 - progress * 0.5,
        }}
      />
    </div>
  )
}
