/**
 * Money arithmetic for an incident.
 *
 * Every panel on the console reads its figures from here rather than computing
 * its own. If the timeline and the ledger disagreed about how much had reached
 * cash-out, a judge would notice, and there would be no good answer.
 */

import type { IncidentGraph } from '@/api/client'

export function exitIds(graph: IncidentGraph): Set<string> {
  return new Set(graph.nodes.filter((n) => n.kind === 'exit').map((n) => n.id))
}

/** Links carry endpoints as ids; the force simulation may swap in objects. */
function endpoint(value: string | { id: string }): string {
  return typeof value === 'string' ? value : value.id
}

export interface Exposure {
  /** Fraud rupees that have left the banking system by this minute. */
  cashedOut: number
  /** Of the stolen amount, what is still inside the banking system. */
  stillInside: number
  /** Distinct cash-out points used so far. */
  exitsUsed: number
  /** Mule accounts the money has reached so far. */
  mulesReached: number
  /** Distinct banks those mule accounts sit across. */
  banksTouched: number
  /** Minute the first rupee left, or null if none has. */
  firstExitMinute: number | null
}

export function exposureAt(
  graph: IncidentGraph,
  minute: number,
  stolen: number,
): Exposure {
  const exits = exitIds(graph)
  const usedExits = new Set<string>()
  const banks = new Set<string>()

  let cashedOut = 0
  let firstExitMinute: number | null = null

  for (const link of graph.links) {
    if (!link.is_fraud || link.minute > minute) continue
    const target = endpoint(link.target)
    if (!exits.has(target)) continue

    cashedOut += link.amount
    usedExits.add(target)
    firstExitMinute =
      firstExitMinute === null ? link.minute : Math.min(firstExitMinute, link.minute)
  }

  let mulesReached = 0
  for (const node of graph.nodes) {
    if (node.kind !== 'mule') continue
    if (node.first_seen_minute < 0 || node.first_seen_minute > minute) continue
    mulesReached += 1
    banks.add(node.bank_id)
  }

  // Cash-out is measured across every fraud episode inside the window, so it
  // can exceed this one victim's loss. Clamp rather than show a negative.
  const attributable = Math.min(cashedOut, stolen)

  return {
    cashedOut,
    stillInside: Math.max(0, stolen - attributable),
    exitsUsed: usedExits.size,
    mulesReached,
    banksTouched: banks.size,
    firstExitMinute,
  }
}

export interface FlowBucket {
  /** Minute at the start of the bucket. */
  minute: number
  /** Fraud value moving between accounts inside the banking system. */
  internal: number
  /** Fraud value leaving the banking system. */
  exit: number
}

/** Bucketed fraud flow over the horizon, for the timeline histogram. */
export function flowSeries(graph: IncidentGraph, buckets = 140): FlowBucket[] {
  const horizon = Math.max(1, graph.horizon_minutes)
  const width = horizon / buckets
  const exits = exitIds(graph)

  const series: FlowBucket[] = Array.from({ length: buckets }, (_, i) => ({
    minute: Math.round(i * width),
    internal: 0,
    exit: 0,
  }))

  for (const link of graph.links) {
    if (!link.is_fraud || link.minute < 0) continue
    const index = Math.min(buckets - 1, Math.floor(link.minute / width))
    const bucket = series[index]
    if (!bucket) continue

    if (exits.has(endpoint(link.target))) bucket.exit += link.amount
    else bucket.internal += link.amount
  }

  return series
}
