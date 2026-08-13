import { AnimatePresence, motion as m } from 'framer-motion'
import { X } from 'lucide-react'
import type { GraphNode } from '@/api/client'
import { archetypeLabel, duration, rupees } from '@/lib/format'
import { tokens } from '@/theme/tokens'

/**
 * Inspect drawer for a single account.
 *
 * Everything shown is measured from the incident graph. Feature attributions
 * and marginal-recovery figures arrive with Phases 3 and 4; the drawer states
 * that plainly rather than filling the space with a placeholder chart.
 */

interface Props {
  node: GraphNode | null
  onClose: () => void
}

const KIND_LABEL: Record<string, string> = {
  victim: 'Victim',
  mule: 'Mule account',
  legit: 'Context account',
  exit: 'Exit point',
}

function kindColor(kind: string): string {
  if (kind === 'mule') return tokens.flow
  if (kind === 'exit') return tokens.burn
  return tokens.textHi
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2 border-b border-ink-line last:border-0">
      <span className="text-[12px] text-lo">{label}</span>
      <span className="font-mono text-[12.5px] text-hi text-right">{value}</span>
    </div>
  )
}

export default function AccountDrawer({ node, onClose }: Props) {
  return (
    <AnimatePresence>
      {node && (
        <m.aside
          key={node.id}
          initial={{ x: 340, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 340, opacity: 0 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
          className="absolute top-0 right-0 h-full w-[340px] bg-ink-raised border-l border-ink-line z-20 overflow-y-auto"
          aria-label={`Account ${node.id}`}
        >
          <div className="flex items-start justify-between px-5 pt-5 pb-4 border-b border-ink-line">
            <div>
              <div className="font-mono text-[15px] text-hi">{node.id}</div>
              <div
                className="text-[12px] mt-1"
                style={{ color: kindColor(node.kind) }}
              >
                {KIND_LABEL[node.kind] ?? node.kind}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close account details"
              className="text-lo hover:text-hi p-1 -m-1"
            >
              <X size={16} strokeWidth={2} />
            </button>
          </div>

          <div className="px-5 py-4">
            <h3 className="label-lo mb-1">Identity</h3>
            <Row label="Bank" value={node.bank_id} />
            <Row label="District" value={node.district} />
            <Row label="Profile" value={archetypeLabel(node.archetype)} />
            {node.exit_kind && <Row label="Exit channel" value={node.exit_kind} />}
          </div>

          <div className="px-5 py-4 border-t border-ink-line">
            <h3 className="label-lo mb-1">Position in this incident</h3>
            <Row
              label="Hops from victim"
              value={node.depth < 0 ? 'not on a path' : node.depth}
            />
            <Row
              label="Money first arrived"
              value={
                node.first_seen_minute < 0 ? '—' : duration(node.first_seen_minute)
              }
            />
            <Row label="Received" value={rupees(node.amount_in)} />
            <Row label="Forwarded" value={rupees(node.amount_out)} />
            <Row
              label="Held"
              value={rupees(Math.max(0, node.amount_in - node.amount_out))}
            />
          </div>

          {node.is_mule && (
            <div className="px-5 py-4 border-t border-ink-line">
              <h3 className="label-lo mb-1">Ring membership</h3>
              <Row label="Ring" value={node.ring_id} />
              <Row label="Layer" value={node.layer_index} />
              <Row
                label="Cashes out"
                value={node.is_cashout_node ? 'yes' : 'no'}
              />
            </div>
          )}

          <div className="px-5 py-4 border-t border-ink-line">
            <p className="text-[12px] text-lo leading-relaxed">
              Feature attributions and the marginal rupees this freeze would save arrive
              with the detector and the solver in Phases 3 and 4.
            </p>
          </div>
        </m.aside>
      )}
    </AnimatePresence>
  )
}
