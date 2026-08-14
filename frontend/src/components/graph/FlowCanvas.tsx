import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d'
import type { GraphLink, GraphNode, IncidentGraph } from '@/api/client'
import { rupeesCompact } from '@/lib/format'
import { tokens } from '@/theme/tokens'

/**
 * The incident flow canvas.
 *
 * Layout is layered left-to-right by hop depth from the victim, which is the
 * reading order of the story: victim on the left, mule layers through the
 * middle, cash-out on the right. X is pinned per node and Y is left to the
 * force simulation, so the graph settles into a readable stack rather than a
 * hairball.
 *
 * Positions seed deterministically from the node id, so the same incident lays
 * out identically every run. A graph that reshuffles between rehearsal and
 * stage is one you cannot talk over.
 *
 * Colour is semantic and the rule is absolute:
 *     amber   = money in motion / at risk
 *     teal    = frozen, money saved
 *     crimson = cash-out, money lost
 * Nothing else on this canvas may use those three.
 */

interface SimNode extends GraphNode {
  x?: number
  y?: number
  fx?: number
}

interface SimLink extends Omit<GraphLink, 'source' | 'target'> {
  source: string | SimNode
  target: string | SimNode
}

interface Props {
  graph: IncidentGraph
  minute: number
  selectedId: string | null
  frozen: Set<string>
  justFrozen: string[]
  onSelect: (node: GraphNode | null) => void
}

/** Stable pseudo-random in [0,1) from a string. Same id, same seat, always. */
function seededUnit(id: string): number {
  let hash = 2166136261
  for (let i = 0; i < id.length; i += 1) {
    hash ^= id.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return ((hash >>> 0) % 10000) / 10000
}

const COLUMN_WIDTH = 210
/** Vertical room allowed per node in a column, in graph units. */
const ROW_PITCH = 15
/** How long a node keeps its arrival highlight, in simulated minutes. */
const ARRIVAL_GLOW_MINUTES = 25
/** How long the freeze pulse lasts, in wall-clock ms. */
const FREEZE_PULSE_MS = 700

function nodeColor(node: GraphNode): string {
  switch (node.kind) {
    case 'victim':
      return tokens.textHi
    case 'mule':
      return tokens.flow
    case 'exit':
      return tokens.burn
    default:
      return tokens.textLo
  }
}

function nodeRadius(node: GraphNode): number {
  if (node.kind === 'victim') return 7.5
  // Size by the victim's money that passed through, not by total volume: a
  // busy merchant that took ₹2,000 of stolen funds should not outweigh a mule
  // holding ₹4,00,000 of them.
  const moved = node.tainted_in > 0 ? node.tainted_in : node.amount_in
  return Math.max(2.5, Math.min(9.5, 2 + Math.log10(1 + moved) * 0.95))
}

export default function FlowCanvas({
  graph,
  minute,
  selectedId,
  frozen,
  justFrozen,
  onSelect,
}: Props) {
  const ref = useRef<ForceGraphMethods<SimNode, SimLink> | undefined>(undefined)
  const wrapper = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const pulseStart = useRef<Map<string, number>>(new Map())

  const reduceMotion = useMemo(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    [],
  )

  // Record when each account was frozen, so the pulse can decay from that
  // moment rather than restarting on every render.
  useEffect(() => {
    const now = performance.now()
    for (const id of justFrozen) {
      if (!pulseStart.current.has(id)) pulseStart.current.set(id, now)
    }
  }, [justFrozen])

  useEffect(() => {
    pulseStart.current.clear()
  }, [graph.scenario_id])

  useEffect(() => {
    const element = wrapper.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const { data, columns, labelY } = useMemo(() => {
    // Height each column needs is driven by how many nodes are in it, not by a
    // fixed constant. A layer of six and a layer of ninety spread over the same
    // 950px otherwise leaves the small one as a sparse dotted line and the
    // large one as an unreadable stripe.
    const perDepth = new Map<number, number>()
    for (const node of graph.nodes) {
      const depth = node.depth < 0 ? -1 : node.depth
      perDepth.set(depth, (perDepth.get(depth) ?? 0) + 1)
    }
    const widest = Math.max(...perDepth.values(), 1)

    const nodes: SimNode[] = graph.nodes.map((node) => {
      // Context accounts sit off no path from the victim (depth -1). Park them
      // in a gutter to the left instead of letting them drift through the
      // middle of the laundering chain.
      const raw = node.depth < 0 ? -1 : node.depth
      const depth = node.depth < 0 ? -0.8 : node.depth
      const inColumn = perDepth.get(raw) ?? 1
      // Scale the column's height by its share of the widest one, so every
      // layer reads at a similar density.
      const spread = ROW_PITCH * Math.max(inColumn, 4) * (0.55 + 0.45 * (inColumn / widest))

      return {
        ...node,
        fx: depth * COLUMN_WIDTH,
        x: depth * COLUMN_WIDTH,
        y: (seededUnit(node.id) - 0.5) * spread,
      }
    })

    const depths = [...new Set(graph.nodes.map((n) => n.depth))]
      .filter((d) => d >= 0)
      .sort((a, b) => a - b)

    const tallest = ROW_PITCH * widest
    return {
      data: { nodes, links: graph.links.map((link) => ({ ...link })) as SimLink[] },
      columns: depths,
      labelY: -(tallest / 2) - 26,
    }
  }, [graph])

  useEffect(() => {
    ref.current?.d3Force('charge')?.strength(-40)
  }, [graph.scenario_id])

  // Fit once the simulation has actually settled. Fitting on a timer races the
  // layout: the nodes are still moving, so the view ends up framed on wherever
  // they happened to be a few hundred milliseconds in.
  const fit = useCallback(() => {
    ref.current?.zoomToFit(600, 60)
  }, [])

  const drawNode = useCallback(
    (raw: SimNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const x = raw.x ?? 0
      const y = raw.y ?? 0
      const radius = nodeRadius(raw)
      const selected = raw.id === selectedId
      const isFrozen = frozen.has(raw.id)

      const reached = raw.first_seen_minute >= 0 && raw.first_seen_minute <= minute
      const isContext = raw.kind === 'legit' && raw.depth < 0
      const sinceArrival = reached ? minute - raw.first_seen_minute : Infinity
      const glow = Math.max(0, 1 - sinceArrival / ARRIVAL_GLOW_MINUTES)

      // Accounts the money has not reached yet stay dark. This is what turns
      // the canvas from a picture into a sequence.
      ctx.globalAlpha = isContext ? 0.22 : reached || isFrozen ? 1 : 0.16

      if (reached && glow > 0 && !isContext && !isFrozen) {
        ctx.beginPath()
        ctx.arc(x, y, radius + 5 * glow, 0, 2 * Math.PI)
        ctx.fillStyle = nodeColor(raw)
        ctx.globalAlpha = 0.18 * glow
        ctx.fill()
        ctx.globalAlpha = 1
      }

      ctx.beginPath()
      ctx.arc(x, y, radius, 0, 2 * Math.PI)
      ctx.fillStyle = isFrozen ? tokens.interdict : nodeColor(raw)
      ctx.fill()
      ctx.globalAlpha = 1

      if (isFrozen) {
        // The teal ring, plus a short outward pulse at the moment it lands.
        const started = pulseStart.current.get(raw.id)
        const age = started === undefined ? Infinity : performance.now() - started
        const pulse = reduceMotion ? 0 : Math.max(0, 1 - age / FREEZE_PULSE_MS)

        ctx.beginPath()
        ctx.arc(x, y, radius + 3 + pulse * 7, 0, 2 * Math.PI)
        ctx.strokeStyle = tokens.interdict
        ctx.lineWidth = (pulse > 0 ? 1.8 : 1.2) / scale
        ctx.globalAlpha = pulse > 0 ? 0.35 + 0.65 * pulse : 0.85
        ctx.stroke()
        ctx.globalAlpha = 1
      } else if (raw.is_cashout_node && raw.kind === 'mule' && reached) {
        // A mule that touches an exit is where money actually leaves.
        ctx.strokeStyle = tokens.burn
        ctx.lineWidth = 1.3 / scale
        ctx.stroke()
      }

      if (selected) {
        ctx.beginPath()
        ctx.arc(x, y, radius + 5.5, 0, 2 * Math.PI)
        ctx.strokeStyle = tokens.textHi
        ctx.lineWidth = 1.5 / scale
        ctx.stroke()
      }

      if (raw.kind === 'victim' && scale > 0.4) {
        ctx.font = `500 ${13 / scale}px "IBM Plex Mono", monospace`
        ctx.fillStyle = tokens.textHi
        ctx.textAlign = 'center'
        ctx.fillText('victim', x, y - radius - 8 / scale)
      }
    },
    [selectedId, minute, frozen, reduceMotion],
  )

  // Column headers, drawn in graph space so they track zoom and pan.
  const drawColumns = useCallback(
    (ctx: CanvasRenderingContext2D, scale: number) => {
      if (scale < 0.22) return
      ctx.textAlign = 'center'
      ctx.font = `500 ${12 / scale}px "IBM Plex Mono", monospace`

      for (const depth of columns) {
        ctx.fillStyle = tokens.textLo
        ctx.globalAlpha = 0.55
        const label = depth === 0 ? 'victim' : `layer ${depth}`
        ctx.fillText(label, depth * COLUMN_WIDTH, labelY)
        ctx.globalAlpha = 1
      }
    },
    [columns, labelY],
  )

  /** An edge out of a frozen account is dark: nothing moves through it. */
  const isBlocked = useCallback(
    (link: SimLink): boolean => {
      const source = typeof link.source === 'string' ? link.source : link.source.id
      return frozen.has(source)
    },
    [frozen],
  )

  return (
    <div ref={wrapper} className="w-full h-full">
      {size.width > 0 && (
        <ForceGraph2D<SimNode, SimLink>
          ref={ref}
          width={size.width}
          height={size.height}
          graphData={data}
          backgroundColor={tokens.ink}
          nodeRelSize={1}
          nodeCanvasObject={drawNode}
          onRenderFramePost={drawColumns}
          nodeLabel={(node) =>
            `<div style="font-family:'IBM Plex Mono',monospace;font-size:11px;background:${tokens.inkRaised};border:1px solid ${tokens.inkLine};padding:5px 7px;border-radius:3px;color:${tokens.textHi}">${node.id}<br/><span style="color:${tokens.textLo}">${node.bank_id} · ${rupeesCompact(node.tainted_in)} of the victim's money${frozen.has(node.id) ? ' · frozen' : ''}</span></div>`
          }
          nodePointerAreaPaint={(node, color, ctx) => {
            ctx.fillStyle = color
            ctx.beginPath()
            ctx.arc(node.x ?? 0, node.y ?? 0, nodeRadius(node) + 3, 0, 2 * Math.PI)
            ctx.fill()
          }}
          // Only *this victim's* money is drawn. Context accounts stay on the
          // canvas as dim points -- they are why precision is hard -- but
          // their ordinary traffic is not, and neither is other victims' money
          // moving through the same ring in the same window. Both produced
          // long edges across every column that buried the one path that
          // matters.
          linkVisibility={(link) => link.tainted > 0 && link.minute <= minute}
          linkColor={(link) => (isBlocked(link) ? tokens.inkLine : tokens.flow)}
          linkWidth={(link) => (isBlocked(link) ? 0.5 : 1)}
          linkDirectionalParticles={
            reduceMotion
              ? 0
              : (link) =>
                  link.minute <= minute && !isBlocked(link)
                    ? // Particle count tracks log(amount), so a large transfer
                      // visibly carries more money than a small one.
                      Math.max(1, Math.min(5, Math.round(Math.log10(1 + link.tainted) - 1)))
                    : 0
          }
          linkDirectionalParticleWidth={1.9}
          linkDirectionalParticleColor={() => tokens.flow}
          linkDirectionalArrowLength={2.6}
          linkDirectionalArrowRelPos={1}
          onNodeClick={(node) => onSelect(node)}
          onBackgroundClick={() => onSelect(null)}
          onEngineStop={fit}
          cooldownTicks={90}
          d3VelocityDecay={0.45}
          enableNodeDrag={false}
        />
      )}
    </div>
  )
}
