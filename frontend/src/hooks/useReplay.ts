import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * The incident replay clock.
 *
 * Drives a simulated-minute cursor across the incident horizon. Everything on
 * the console reads from this one value, so the graph, the timeline and the
 * ledger figures can never disagree about what time it is -- which is exactly
 * the failure a client-side animation timer produces when it drifts away from
 * the data it is supposed to be showing.
 */

export interface Replay {
  /** Current position, in minutes after the incident. */
  minute: number
  playing: boolean
  speed: number
  atEnd: boolean
  play: () => void
  pause: () => void
  toggle: () => void
  restart: () => void
  scrub: (minute: number) => void
  setSpeed: (speed: number) => void
  jumpToEnd: () => void
}

export const SPEEDS = [1, 2, 4] as const

/** A full 6-hour horizon plays in about this long at 1x. */
const BASE_PLAYTHROUGH_SECONDS = 14

/**
 * @param maxMinute end of the horizon
 * @param resetKey  changing this restarts the clock -- pass the incident id,
 *                  since every incident shares the same horizon length and
 *                  `maxMinute` alone would not change between them
 */
export function useReplay(
  maxMinute: number,
  resetKey: string | number,
  autoPlay = true,
): Replay {
  const reduceMotion = useRef(
    typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  const [minute, setMinute] = useState(() => (reduceMotion.current ? maxMinute : 0))
  const [playing, setPlaying] = useState(autoPlay && !reduceMotion.current)
  const [speed, setSpeed] = useState(1)

  // A new incident resets the clock and starts again from the beginning.
  useEffect(() => {
    if (reduceMotion.current) {
      setMinute(maxMinute)
      setPlaying(false)
      return
    }
    setMinute(0)
    setPlaying(autoPlay)
  }, [resetKey, maxMinute, autoPlay])

  useEffect(() => {
    if (!playing || maxMinute <= 0) return

    const perSecond = (maxMinute / BASE_PLAYTHROUGH_SECONDS) * speed
    let frame = 0
    let last = performance.now()

    const step = (now: number) => {
      const delta = (now - last) / 1000
      last = now

      setMinute((current) => {
        const next = current + delta * perSecond
        if (next >= maxMinute) {
          setPlaying(false)
          return maxMinute
        }
        return next
      })

      frame = requestAnimationFrame(step)
    }

    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [playing, speed, maxMinute])

  const restart = useCallback(() => {
    setMinute(0)
    setPlaying(true)
  }, [])

  const toggle = useCallback(() => {
    setPlaying((was) => {
      // Pressing play at the very end should replay rather than sit still.
      if (!was && minute >= maxMinute) setMinute(0)
      return !was
    })
  }, [minute, maxMinute])

  const scrub = useCallback((next: number) => {
    setPlaying(false)
    setMinute(next)
  }, [])

  return {
    minute,
    playing,
    speed,
    atEnd: minute >= maxMinute,
    play: () => setPlaying(true),
    pause: () => setPlaying(false),
    toggle,
    restart,
    scrub,
    setSpeed,
    jumpToEnd: () => {
      setPlaying(false)
      setMinute(maxMinute)
    },
  }
}
