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
/**
 * The distribution of member scores, instead of one saturated average.
 *
 * "Mean p(mule) 100%" on every card reads as leakage to a sceptical judge, and
 * they reach that conclusion several screens before they reach the caveat in
 * the README. The number is not wrong -- these accounts are already known to
 * have received money traced from a live complaint minutes earlier, which is a
 * far easier problem than standing detection -- but a single saturated figure
 * cannot say that, and a min and a median can.
 *
 * Grey, not amber: this is a model output, not money.
 */
function ScoreSpread({ ring }: { ring: DiscoveredRing }) {
  const peak = Math.max(1, ...ring.p_mule_histogram)

  return (
    <div>
      <div className="flex items-baseline justify-between text-[13px] mb-1">
        <span className="text-lo">p(mule) across members</span>
        <span className="font-mono text-hi tabular-nums">
          min {percent(ring.p_mule_min, 0)} · med {percent(ring.p_mule_median, 0)}
        </span>
      </div>
      <div
        className="flex items-end gap-px h-5"
        role="img"
        aria-label={`Score distribution: minimum ${percent(
          ring.p_mule_min,
          0,
        )}, median ${percent(ring.p_mule_median, 0)}`}
      >
        {ring.p_mule_histogram.map((value, index) => (
          <span
            key={index}
            className="flex-1 bg-lo/45 rounded-[1px]"
            style={{ height: `${Math.max(value > 0 ? 12 : 3, (value / peak) * 100)}%` }}
          />
        ))}
      </div>
      <div className="flex justify-between text-[10.5px] text-lo/70 mt-0.5">
        <span>0</span>
        <span>1</span>
      </div>
    </div>
  )
}

export default function RingCard({ ring }: { ring: DiscoveredRing }) {
  const perDevice = ring.accounts / Math.max(1, ring.device_clusters)
  const shared = ring.device_clusters < ring.accounts

  return (
    <article className="panel p-4 flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-[15.5px] text-hi">{ring.ring_id}</span>
        <span className="text-[13px] text-lo">
          confidence {percent(ring.confidence, 0)}
        </span>
      </div>

      <div className="flex items-baseline gap-1.5">
        <span className="font-mono text-[25px] text-flow leading-none tabular-nums">
          {rupeesCompact(ring.total_flow_inr)}
        </span>
        <span className="text-[13px] text-lo">moved</span>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[14px]">
        {[
          ['Accounts', count(ring.accounts)],
          ['Banks', String(ring.banks.length)],
          ['Devices', String(ring.device_clusters)],
          ['IP ranges', String(ring.ip_clusters)],
          ['Districts', String(ring.districts)],
        ].map(([label, value]) => (
          <div key={label} className="flex justify-between">
            <dt className="text-lo">{label}</dt>
            <dd className="font-mono text-hi tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>

      <ScoreSpread ring={ring} />

      {ring.cashout_capacity_inr > 0 && (
        <div className="flex justify-between text-[14px]">
          <span className="text-lo">Cashed out</span>
          <span className="font-mono text-burn tabular-nums">
            {rupeesCompact(ring.cashout_capacity_inr)}
          </span>
        </div>
      )}

      <p className="text-[13.5px] text-lo leading-relaxed pt-2 border-t border-ink-line">
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
            className="font-mono text-[12px] text-lo border border-ink-line rounded-panel px-1.5 py-0.5"
          >
            {bank}
          </span>
        ))}
      </div>
    </article>
  )
}
