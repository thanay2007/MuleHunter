import type { DiscoveredRing } from '@/api/client'
import { count, percent, rupeesCompact } from '@/lib/format'

/**
 * One community the clustering found.
 *
 * The device count is the line that carries the argument: a rule engine
 * scoring these accounts one at a time sees N unrelated grey accounts, because
 * the evidence lives in the neighbourhood rather than in any single account's
 * features. Nine accounts operating from three handsets is not nine people.
 */
export default function RingCard({ ring }: { ring: DiscoveredRing }) {
  const perDevice = ring.accounts / Math.max(1, ring.device_clusters)
  const shared = ring.device_clusters < ring.accounts

  return (
    <article className="panel p-4 flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-[13px] text-hi">{ring.ring_id}</span>
        <span className="text-[11px] text-lo">
          confidence {percent(ring.confidence, 0)}
        </span>
      </div>

      <div className="flex items-baseline gap-1.5">
        <span className="font-mono text-[24px] text-flow leading-none tabular-nums">
          {rupeesCompact(ring.total_flow_inr)}
        </span>
        <span className="text-[11px] text-lo">moved</span>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12px]">
        {[
          ['Accounts', count(ring.accounts)],
          ['Banks', String(ring.banks.length)],
          ['Devices', String(ring.device_clusters)],
          ['IP ranges', String(ring.ip_clusters)],
          ['Districts', String(ring.districts)],
          ['Mean p(mule)', percent(ring.mean_p_mule, 0)],
        ].map(([label, value]) => (
          <div key={label} className="flex justify-between">
            <dt className="text-lo">{label}</dt>
            <dd className="font-mono text-hi tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>

      {ring.cashout_capacity_inr > 0 && (
        <div className="flex justify-between text-[12px]">
          <span className="text-lo">Reached cash-out</span>
          <span className="font-mono text-burn tabular-nums">
            {rupeesCompact(ring.cashout_capacity_inr)}
          </span>
        </div>
      )}

      <p className="text-[11.5px] text-lo leading-relaxed pt-2 border-t border-ink-line">
        {shared ? (
          <>
            {ring.accounts} accounts across {ring.banks.length}{' '}
            {ring.banks.length === 1 ? 'bank' : 'banks'}, operating from{' '}
            <span className="text-hi">{ring.device_clusters} devices</span> — an
            average of {perDevice.toFixed(1)} accounts per handset.
          </>
        ) : (
          <>
            {ring.accounts} accounts across {ring.banks.length}{' '}
            {ring.banks.length === 1 ? 'bank' : 'banks'}, each on its own device.
            This group was found by how the money moves, not by shared hardware.
          </>
        )}
      </p>

      <div className="flex flex-wrap gap-1">
        {ring.banks.map((bank) => (
          <span
            key={bank}
            className="font-mono text-[10px] text-lo border border-ink-line rounded-panel px-1.5 py-0.5"
          >
            {bank}
          </span>
        ))}
      </div>
    </article>
  )
}
