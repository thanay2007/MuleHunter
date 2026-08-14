import { useEffect, useRef, useState } from 'react'
import { rupees } from '@/lib/format'

/**
 * A rupee figure that ramps to its new value instead of jumping.
 *
 * Tabular mono, so digits never shift width as they count. A figure that
 * reflows while a judge is reading it undermines every number on the page.
 *
 * The ramp is eased over ~800ms and honours `prefers-reduced-motion`, where it
 * snaps to the value directly -- the number still updates, it just does not
 * animate.
 */

const RAMP_MS = 800

function easeOutCubic(t: number): number {
  return 1 - (1 - t) ** 3
}

interface Props {
  value: number
  className?: string
}

export default function RecoveryCounter({ value, className = '' }: Props) {
  const [shown, setShown] = useState(value)
  const from = useRef(value)
  const frame = useRef(0)

  useEffect(() => {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduceMotion) {
      from.current = value
      setShown(value)
      return
    }

    const start = performance.now()
    const origin = from.current
    const delta = value - origin
    if (delta === 0) return

    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / RAMP_MS)
      setShown(origin + delta * easeOutCubic(progress))
      if (progress < 1) {
        frame.current = requestAnimationFrame(step)
      } else {
        from.current = value
      }
    }

    frame.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame.current)
  }, [value])

  return (
    <span className={`font-mono tabular-nums ${className}`}>{rupees(shown)}</span>
  )
}
