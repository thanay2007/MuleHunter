import { useQuery } from '@tanstack/react-query'
import type { Ring } from '@/api/client'
import { api } from '@/api/client'
import { count, rupeesCompact, typologyLabel } from '@/lib/format'

/**
 * Ring browser. Every figure is computed from the generated dataset, including
 * the device-cluster count -- which is the number that makes the argument:
 * 34 accounts operating from 7 handsets is not 34 unrelated people.
 */

function RingCard({ ring }: { ring: Ring }) {
  const accountsPerDevice = ring.accounts / Math.max(1, ring.device_clusters)

  return (
    <article className="panel p-4 flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-[13px] text-hi">{ring.ring_id}</span>
        <span className="text-[11px] text-lo">{typologyLabel(ring.typology)}</span>
      </div>

      <div className="flex items-baseline gap-1.5">
        <span className="font-mono text-[24px] text-flow leading-none">
          {rupeesCompact(ring.total_flow_inr)}
        </span>
        <span className="text-[11px] text-lo">moved</span>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12px]">
        <div className="flex justify-between">
          <dt className="text-lo">Accounts</dt>
          <dd className="font-mono text-hi">{ring.accounts}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-lo">Banks</dt>
          <dd className="font-mono text-hi">{ring.banks.length}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-lo">Devices</dt>
          <dd className="font-mono text-hi">{ring.device_clusters}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-lo">Layers</dt>
          <dd className="font-mono text-hi">{ring.max_layer}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-lo">Cash-out</dt>
          <dd className="font-mono text-hi">{ring.cashout_nodes}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-lo">Transfers</dt>
          <dd className="font-mono text-hi">{count(ring.txn_count)}</dd>
        </div>
      </dl>

      <p className="text-[11.5px] text-lo leading-relaxed pt-2 border-t border-ink-line">
        {ring.accounts} accounts across {ring.banks.length} banks, operating from{' '}
        <span className="text-hi">{ring.device_clusters} devices</span> — an average of{' '}
        {accountsPerDevice.toFixed(1)} accounts per handset.
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

export default function Rings() {
  const { data, isPending, error } = useQuery({ queryKey: ['rings'], queryFn: api.rings })

  if (isPending) {
    return <p className="p-8 text-[13px] text-lo">Loading rings…</p>
  }
  if (error) {
    return <p className="p-8 text-[13px] text-lo">{(error as Error).message}</p>
  }

  return (
    <div className="h-full overflow-y-auto p-5">
      <header className="mb-5">
        <h1 className="font-display text-lg text-hi tracking-display">
          Detected ring structure
        </h1>
        <p className="text-[13px] text-lo mt-1 max-w-3xl leading-relaxed">
          Twelve rings across four typologies. The device count is the point: a rule engine
          scoring these accounts one at a time sees unrelated grey accounts, because the
          evidence lives in the neighbourhood rather than in any single account&apos;s
          features.
        </p>
      </header>

      <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-3">
        {data.map((ring) => (
          <RingCard key={ring.ring_id} ring={ring} />
        ))}
      </div>
    </div>
  )
}
