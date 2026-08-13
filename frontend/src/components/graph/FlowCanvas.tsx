import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d'
import type { GraphLink, GraphNode, IncidentGraph } from '@/api/client'
import { tokens } from '@/theme/tokens'

/**
 * The incident flow canvas.
 *
 * Layout is layered left-to-right by hop depth from the victim, which is the
 * reading order of the story: victim on the left, mule layers in the middle,
 * cash-out on the right. X is pinned per node and Y is left to the force
 * simulation, so the graph settles into a readable stack rather than a hairball.
 *
 * Positions are seeded deterministically from the node id. The same incident
 * must lay out identically every run -- a graph that reshuffles between
 * rehearsal and stage is a demo you cannot talk over.
 */

interface SimNode extends GraphNode {
  x?: number
  y?: number
  fx?: number
  vy?: number
}

interface SimLink extends Omit<GraphLink, 'source' | 'target'> {
  source: string | SimNode
  target: string | SimNode
}

interface Props {
  graph: IncidentGraph
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

const COLUMN_WIDTH = 190

function nodeColor(node: GraphNode): string {
  // Colour is semantic and the rule is absolute:
  //   amber = money at risk, crimson = money lost, teal = money saved.
  // Legitimate context accounts get no money colour at all, because no money
  // of the victim's is riding on them.
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
  const moved = node.amount_in + node.amount_out
  if (node.kind === 'victim') return 7
  return Math.max(2.5, Math.min(9, 2 + Math.log10(1 + moved) * 0.95))
}

export default function FlowCanvas({ graph, selectedId, onSelect }: Props) {
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

  const data = useMemo(() => {
    const maxDepth = Math.max(1, ...graph.nodes.map((n) => n.depth))
    const nodes: SimNode[] = graph.nodes.map((node) => {
      // Context accounts have no path from the victim (depth -1); park them
      // in a gutter to the left rather than letting them float through the
      // middle of the laundering chain.
      const depth = node.depth < 0 ? -0.6 : node.depth
      return {
        ...node,
        fx: depth * COLUMN_WIDTH,
        x: depth * COLUMN_WIDTH,
        y: (seededUnit(node.id) - 0.5) * 900,
      }
    })
    const links: SimLink[] = graph.links.map((link) => ({ ...link }))
    return { nodes, links, maxDepth }
  }, [graph])

  useEffect(() => {
    const instance = ref.current
    if (!instance) return
    instance.d3Force('charge')?.strength(-38)
    // Zoom to fit once the layout has settled.
    const timer = window.setTimeout(() => instance.zoomToFit(600, 70), 420)
    return () => window.clearTimeout(timer)
  }, [graph.scenario_id])

  const drawNode = useCallback(
    (raw: SimNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const x = raw.x ?? 0
      const y = raw.y ?? 0
      const radius = nodeRadius(raw)
      const selected = raw.id === selectedId

      ctx.beginPath()
      ctx.arc(x, y, radius, 0, 2 * Math.PI)
      ctx.fillStyle = nodeColor(raw)
      ctx.globalAlpha = raw.kind === 'legit' ? 0.5 : 1
      ctx.fill()
      ctx.globalAlpha = 1

      if (raw.is_cashout_node && raw.kind === 'mule') {
        // A mule that touches an exit is where money actually leaves.
        ctx.strokeStyle = tokens.burn
        ctx.lineWidth = 1.2 / scale
        ctx.stroke()
      }

      if (selected) {
        ctx.beginPath()
        ctx.arc(x, y, radius + 4, 0, 2 * Math.PI)
        ctx.strokeStyle = tokens.textHi
        ctx.lineWidth = 1.4 / scale
        ctx.stroke()
      }

      if (raw.kind === 'victim' && scale > 0.45) {
        ctx.font = `500 ${11 / scale}px "IBM Plex Mono", monospace`
        ctx.fillStyle = tokens.textHi
        ctx.textAlign = 'center'
        ctx.fillText('victim', x, y - radius - 7 / scale)
      }
    },
    [selectedId],
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
          nodePointerAreaPaint={(node, color, ctx) => {
            ctx.fillStyle = color
            ctx.beginPath()
            ctx.arc(node.x ?? 0, node.y ?? 0, nodeRadius(node) + 3, 0, 2 * Math.PI)
            ctx.fill()
          }}
          linkColor={(link) => (link.is_fraud ? tokens.flow : tokens.inkLine)}
          linkWidth={(link) => (link.is_fraud ? 0.9 : 0.4)}
          linkDirectionalParticles={reduceMotion ? 0 : (link) => (link.is_fraud ? 2 : 0)}
          linkDirectionalParticleWidth={1.8}
          linkDirectionalParticleColor={() => tokens.flow}
          linkDirectionalArrowLength={2.5}
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
