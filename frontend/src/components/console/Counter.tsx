import { useEffect, useRef, useState } from 'react'
import { motion as m } from 'framer-motion'

/**
 * A rupee figure that counts up with an eased ramp.
 *
 * Rendered in tabular mono so digits never change width -- a counter that
 * jitters horizontally as it climbs reads as unfinished software, and this is
 * the number the judge is looking at.
 */

interface Props {
  value: number
  format: (value: number) => string
  durationMs?: number
  className?: string
}

const easeOutCubic = (t: number): number => 1 - (1 - t) ** 3

export default function Counter({ value, format, durationMs = 800, className }: Props) {
  const [shown, setShown] = useState(0)
  const frame = useRef<number>(0)
  const reduceMotion = useRef(
    typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  useEffect(() => {
    if (reduceMotion.current) {
      setShown(value)
      return
    }

    const from = 0
    const started = performance.now()

    const tick = (now: number) => {
      const progress = Math.min(1, (now - started) / durationMs)
      setShown(from + (value - from) * easeOutCubic(progress))
      if (progress < 1) frame.current = requestAnimationFrame(tick)
    }

    frame.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame.current)
  }, [value, durationMs])

  return (
    <m.span
      key={value}
      initial={{ opacity: 0.6 }}
      animate={{ opacity: 1 }}
      className={`font-mono tabular-nums ${className ?? ''}`}
    >
      {format(shown)}
    </m.span>
  )
}
