import { useCallback, useEffect, useRef, useState } from 'react'
import { replayUrl, type PolicyId } from '@/api/client'

/**
 * The incident replay, driven by the server.
 *
 * Frames arrive over a WebSocket, one per simulated minute, at a rate the
 * server sets. The console renders whatever the latest frame says and never
 * advances the clock on its own.
 *
 * That constraint is the whole design. A client-side timer animating between
 * fetched totals drifts away from the data within seconds, and the first thing
 * a judge notices is a rupee counter that disagrees with the graph next to it.
 * Here there is only one clock and the server owns it.
 */

export interface ReplayFlow {
  src: string
  dst: string
  amount: number
  tainted: number
}

export interface ReplaySide {
  recovered_inr: number
  leaked_inr: number
  at_risk_inr: number
  frozen: string[]
}

export interface ReplayFrame {
  minute: number
  flows: ReplayFlow[]
  frozen: string[]
  recovered_inr: number
  leaked_inr: number
  at_risk_inr: number
  frontier_accounts: string[]
  baseline: ReplaySide
}

export interface ReplayHeader {
  scenario_id: string
  policy: string
  amount_inr: number
  complaint_minute: number
  horizon_minutes: number
  fps: number
  plan_size: number
  already_gone_inr: number
  final: {
    chakravyuh: SideTotals
    baseline: SideTotals
  }
}

export interface SideTotals {
  leaked_inr: number
  secured_inr: number
  residual_inr: number
  innocent_frozen: number
  mules_frozen: number
  frozen: number
}

export type StreamStatus = 'idle' | 'connecting' | 'streaming' | 'done' | 'error'

export interface ReplayStream {
  status: StreamStatus
  header: ReplayHeader | null
  frame: ReplayFrame | null
  /** Every account frozen so far, for the canvas. */
  frozen: Set<string>
  /** Accounts frozen in the most recent frame -- these get the pulse. */
  justFrozen: string[]
  error: string | null
  start: () => void
  stop: () => void
}

const EMPTY_FROZEN: Set<string> = new Set()

export function useReplayStream(
  scenarioId: string | null,
  policy: PolicyId,
  budgetK: number,
  innocenceBudget: number,
  adaptiveAdversary: boolean,
  fps: number,
): ReplayStream {
  const [status, setStatus] = useState<StreamStatus>('idle')
  const [header, setHeader] = useState<ReplayHeader | null>(null)
  const [frame, setFrame] = useState<ReplayFrame | null>(null)
  const [frozen, setFrozen] = useState<Set<string>>(EMPTY_FROZEN)
  const [justFrozen, setJustFrozen] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  const socket = useRef<WebSocket | null>(null)
  const previousFrozen = useRef<Set<string>>(EMPTY_FROZEN)

  const stop = useCallback(() => {
    socket.current?.close()
    socket.current = null
  }, [])

  const start = useCallback(() => {
    if (!scenarioId) return
    stop()

    setStatus('connecting')
    setHeader(null)
    setFrame(null)
    setFrozen(EMPTY_FROZEN)
    setJustFrozen([])
    setError(null)
    previousFrozen.current = EMPTY_FROZEN

    const ws = new WebSocket(
      replayUrl(scenarioId, {
        policy,
        budgetK,
        innocenceBudget,
        adaptiveAdversary,
        fps,
      }),
    )
    socket.current = ws

    ws.onmessage = (event: MessageEvent<string>) => {
      const message = JSON.parse(event.data) as
        | ({ type: 'header' } & ReplayHeader)
        | ({ type: 'frame' } & ReplayFrame)
        | { type: 'end'; minute: number }
        | { type: 'error'; detail: string }

      if (message.type === 'header') {
        setHeader(message)
        setStatus('streaming')
        return
      }
      if (message.type === 'frame') {
        setFrame(message)
        const next = new Set(message.frozen)
        const added = message.frozen.filter((id) => !previousFrozen.current.has(id))
        if (added.length) setJustFrozen(added)
        previousFrozen.current = next
        setFrozen(next)
        return
      }
      if (message.type === 'end') {
        setStatus('done')
        return
      }
      setError(message.detail)
      setStatus('error')
    }

    ws.onerror = () => {
      setError('The replay stream dropped. Is the backend still running?')
      setStatus('error')
    }
    ws.onclose = () => {
      socket.current = null
      // A close after the final frame is the normal ending, not a failure.
      setStatus((current) => (current === 'streaming' ? 'done' : current))
    }
  }, [scenarioId, policy, budgetK, innocenceBudget, adaptiveAdversary, fps, stop])

  useEffect(() => stop, [stop])

  return { status, header, frame, frozen, justFrozen, error, start, stop }
}
