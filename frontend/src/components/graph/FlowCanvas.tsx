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
 * Positions seed deterministically from the node id. The same incident lays
 * out identically every run -- a graph that reshuffles between rehearsal and
 * stage is one you cannot talk over.
 *
 * The canvas is driven by the replay clock: an edge only appears once the
 * money has actually moved along it, and an account stays dark until the
 * money reaches it.
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

const COLUMN_WIDTH = 200
/** How long a node keeps its arrival highlight, in simulated minutes. */
const ARRIVAL_GLOW_MINUTES = 25

function nodeColor(node: GraphNode): string {
  // Colour is semantic and the rule is absolute:
  //   amber = money at risk, crimson = money lost, teal = money saved.
  // Ordinary accounts get no money colour at all, because none of the
  // victim's money is riding on them.
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
  const moved = node.amount_in + node.amount_out
  return Math.max(2.5, Math.min(9.5, 2 + Math.log10(1 + moved) * 0.95))
}

export default function FlowCanvas({ graph, minute, selectedId, onSelect }: Props) {
  const ref = useRef<ForceGraphMethods<SimNode, SimLink> | undefined>(undefined)
  const wrapper = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })

  const reduceMotion = useMemo(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    [],
  )

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
    const nodes: SimNode[] = graph.nodes.map((node) => {
      // Context accounts sit off no path from the victim (depth -1). Park them
      // in a gutter to the left instead of letting them drift through the
      // middle of the laundering chain.
      const depth = node.depth < 0 ? -0.7 : node.depth
      return {
        ...node,
        fx: depth * COLUMN_WIDTH,
        x: depth * COLUMN_WIDTH,
        y: (seededUnit(node.id) - 0.5) * 950,
      }
    })

    const depths = [...new Set(graph.nodes.map((n) => n.depth))]
      .filter((d) => d >= 0)
      .sort((a, b) => a - b)

    return {
      data: { nodes, links: graph.links.map((link) => ({ ...link })) as SimLink[] },
      columns: depths,
      labelY: -520,
    }
  }, [graph])

  useEffect(() => {
    const instance = ref.current
    if (!instance) return
    instance.d3Force('charge')?.strength(-40)
    const timer = window.setTimeout(() => instance.zoomToFit(650, 80), 450)
    return () => window.clearTimeout(timer)
  }, [graph.scenario_id])

  const drawNode = useCallback(
    (raw: SimNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const x = raw.x ?? 0
      const y = raw.y ?? 0
      const radius = nodeRadius(raw)
      const selected = raw.id === selectedId

      const reached = raw.first_seen_minute >= 0 && raw.first_seen_minute <= minute
      const isContext = raw.kind === 'legit' && raw.depth < 0
      const sinceArrival = reached ? minute - raw.first_seen_minute : Infinity
      const glow = Math.max(0, 1 - sinceArrival / ARRIVAL_GLOW_MINUTES)

      // Accounts the money has not reached yet stay dark. This is what turns
      // the canvas from a picture into a sequence.
      ctx.globalAlpha = isContext ? 0.22 : reached ? 1 : 0.16

      if (reached && glow > 0 && !isContext) {
        ctx.beginPath()
        ctx.arc(x, y, radius + 5 * glow, 0, 2 * Math.PI)
        ctx.fillStyle = nodeColor(raw)
        ctx.globalAlpha = 0.18 * glow
        ctx.fill()
        ctx.globalAlpha = 1
      }

      ctx.beginPath()
      ctx.arc(x, y, radius, 0, 2 * Math.PI)
      ctx.fillStyle = nodeColor(raw)
      ctx.fill()
      ctx.globalAlpha = 1

      if (raw.is_cashout_node && raw.kind === 'mule' && reached) {
        // A mule that touches an exit is where money actually leaves.
        ctx.strokeStyle = tokens.burn
        ctx.lineWidth = 1.3 / scale
        ctx.stroke()
      }

      if (selected) {
        ctx.beginPath()
        ctx.arc(x, y, radius + 4.5, 0, 2 * Math.PI)
        ctx.strokeStyle = tokens.textHi
        ctx.lineWidth = 1.5 / scale
        ctx.stroke()
      }

      if (raw.kind === 'victim' && scale > 0.4) {
        ctx.font = `500 ${11 / scale}px "IBM Plex Mono", monospace`
        ctx.fillStyle = tokens.textHi
        ctx.textAlign = 'center'
        ctx.fillText('victim', x, y - radius - 8 / scale)
      }
    },
    [selectedId, minute],
  )

  // Column headers, drawn in graph space so they track zoom and pan.
  const drawColumns = useCallback(
    (ctx: CanvasRenderingContext2D, scale: number) => {
      if (scale < 0.22) return
      ctx.textAlign = 'center'
      ctx.font = `500 ${10 / scale}px "IBM Plex Mono", monospace`

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
            `<div style="font-family:'IBM Plex Mono',monospace;font-size:11px;background:${tokens.inkRaised};border:1px solid ${tokens.inkLine};padding:5px 7px;border-radius:3px;color:${tokens.textHi}">${node.id}<br/><span style="color:${tokens.textLo}">${node.bank_id} · ${rupeesCompact(node.amount_in)} in</span></div>`
          }
          nodePointerAreaPaint={(node, color, ctx) => {
            ctx.fillStyle = color
            ctx.beginPath()
            ctx.arc(node.x ?? 0, node.y ?? 0, nodeRadius(node) + 3, 0, 2 * Math.PI)
            ctx.fill()
          }}
          linkVisibility={(link) => link.minute <= minute}
          linkColor={(link) => (link.is_fraud ? tokens.flow : tokens.inkLine)}
          linkWidth={(link) => (link.is_fraud ? 1 : 0.4)}
          linkDirectionalParticles={
            reduceMotion ? 0 : (link) => (link.is_fraud && link.minute <= minute ? 2 : 0)
          }
          linkDirectionalParticleWidth={1.9}
          linkDirectionalParticleColor={() => tokens.flow}
          linkDirectionalArrowLength={2.6}
          linkDirectionalArrowRelPos={1}
          onNodeClick={(node) => onSelect(node)}
          onBackgroundClick={() => onSelect(null)}
          cooldownTicks={90}
          d3VelocityDecay={0.45}
          enableNodeDrag={false}
        />
      )}
    </div>
  )
}
