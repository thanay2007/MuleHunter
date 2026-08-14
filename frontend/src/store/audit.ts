import { create } from 'zustand'
import { SESSION_ID } from '@/lib/session'

/**
 * An append-only log of what this session did.
 *
 * Regulators buy auditability. Showing an immutable decision log — what was
 * opened, what was scored, what the solver was asked for, what it returned,
 * what was approved and by whom — is a language financial-services people
 * speak natively, and it costs almost nothing because every one of those
 * events already passes through the console.
 *
 * Append-only is enforced here rather than merely intended: there is no
 * mutate and no remove, only `record`. A log you can edit is not a log.
 *
 * Timestamps are wall-clock on purpose. This records *the sitting*, not the
 * computation — the computation is deterministic and reproducible from the
 * seed, and that is what makes the two worth keeping separately.
 */

export type AuditKind =
  | 'session'
  | 'case'
  | 'solve'
  | 'replay'
  | 'order'
  | 'approval'
  | 'export'

export interface AuditEvent {
  /** Monotonic within the session, so equal timestamps still order. */
  sequence: number
  at: string
  kind: AuditKind
  summary: string
  /** Field/value pairs, rendered as a monospace detail line. */
  detail: Record<string, string | number | boolean>
}

interface AuditState {
  events: AuditEvent[]
  record: (kind: AuditKind, summary: string, detail?: AuditEvent['detail']) => void
}

export const useAudit = create<AuditState>((set) => ({
  events: [
    {
      sequence: 0,
      at: new Date().toISOString(),
      kind: 'session',
      summary: 'Session opened',
      detail: { audit_id: SESSION_ID },
    },
  ],
  record: (kind, summary, detail = {}) =>
    set((state) => ({
      events: [
        ...state.events,
        {
          sequence: state.events.length,
          at: new Date().toISOString(),
          kind,
          summary,
          detail,
        },
      ],
    })),
}))
