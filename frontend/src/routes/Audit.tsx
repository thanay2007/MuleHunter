import { Download, Lock } from 'lucide-react'
import { SESSION_ID } from '@/lib/session'
import { useAudit, type AuditEvent } from '@/store/audit'

/**
 * The session's decision log.
 *
 * Monospace, timestamped, append-only, exportable. Deliberately plain: this is
 * the one screen in the product that should look like a record rather than a
 * presentation, because that is what makes it credible to somebody who has
 * signed off on one.
 */

const KIND_LABEL: Record<AuditEvent['kind'], string> = {
  session: 'SESSION',
  case: 'CASE',
  solve: 'SOLVE',
  replay: 'REPLAY',
  order: 'ORDER',
  approval: 'APPROVAL',
  export: 'EXPORT',
}

function detailLine(detail: AuditEvent['detail']): string {
  return Object.entries(detail)
    .map(([key, value]) => `${key}=${value}`)
    .join('  ')
}

export default function Audit() {
  const events = useAudit((s) => s.events)

  const exportJson = () => {
    const body = JSON.stringify({ audit_id: SESSION_ID, events }, null, 2)
    const url = URL.createObjectURL(new Blob([body], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `chakravyuh-audit-${SESSION_ID.slice(0, 8)}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[1080px] mx-auto px-6 py-5 space-y-4">
        <header className="panel px-5 py-4 flex items-start justify-between gap-6 flex-wrap">
          <div>
            <h1 className="font-display text-[19px] text-hi tracking-display">
              Audit trail
            </h1>
            <p className="text-[13px] text-lo mt-1 flex items-center gap-1.5">
              <Lock size={12} aria-hidden />
              Append-only. {events.length} event
              {events.length === 1 ? '' : 's'} in this session ·{' '}
              <span className="font-mono">{SESSION_ID.slice(0, 8)}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={exportJson}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-panel border border-hi/40 text-[14px] text-hi hover:bg-ink-raised"
          >
            <Download size={13} aria-hidden />
            Export JSON
          </button>
        </header>

        <div className="panel overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-lo">
                {['#', 'Time (UTC)', 'Kind', 'Event', 'Detail'].map((heading) => (
                  <th
                    key={heading}
                    className="text-left font-normal text-[10px] tracking-[0.08em] uppercase px-3 py-2 whitespace-nowrap"
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.sequence} className="border-t border-ink-line align-top">
                  <td className="px-3 py-1.5 font-mono text-lo tabular-nums">
                    {String(event.sequence).padStart(3, '0')}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-lo tabular-nums whitespace-nowrap">
                    {event.at.slice(11, 23)}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-lo whitespace-nowrap">
                    {KIND_LABEL[event.kind]}
                  </td>
                  <td className="px-3 py-1.5 text-hi">{event.summary}</td>
                  <td className="px-3 py-1.5 font-mono text-[12px] text-lo break-all">
                    {detailLine(event.detail) || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="text-[12.5px] text-lo leading-relaxed px-1">
          This log records the sitting, so its timestamps are wall-clock and will
          differ between runs. The decisions it records do not: the same case and
          the same settings produce the same plan and the same freeze order every
          time, from the seed shown in the footer.
        </p>
      </div>
    </div>
  )
}
