import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { api } from '@/api/client'
import RingCard from '@/components/inspect/RingCard'
import ScenarioPicker from '@/components/console/ScenarioPicker'
import { useConsole } from '@/store/console'
import { count, rupeesCompact, typologyLabel } from '@/lib/format'

/**
 * Ring discovery, per incident.
 *
 * These are communities the clustering *found* -- Louvain over an undirected
 * projection combining transfer volume with shared-device and shared-IP edges.
 * They are not the generator's ground-truth rings, which appear separately
 * below so the two can be compared honestly.
 *
 * The shared-infrastructure edges are what make this work. A laundering tree
 * is a tree, so modularity on transfer edges alone splits one ring into
 * several; the device and IP links stitch the branches back together.
 */

export default function Rings() {
  const scenarioId = useConsole((s) => s.scenarioId)
  const setScenario = useConsole((s) => s.setScenario)

  const scenarios = useQuery({ queryKey: ['scenarios'], queryFn: api.scenarios })
  const active = scenarioId ?? scenarios.data?.[0]?.scenario_id ?? null

  const discovered = useQuery({
    queryKey: ['rings-for', active],
    queryFn: () => api.ringsFor(active as string),
    enabled: Boolean(active),
  })

  const truth = useQuery({ queryKey: ['rings'], queryFn: api.rings })

  return (
    <div className="h-full flex">
      <aside className="w-[286px] shrink-0 border-r border-ink-line overflow-y-auto px-4 py-4">
        <h2 className="label-lo mb-2">Incident</h2>
        {scenarios.data ? (
          <ScenarioPicker
            scenarios={scenarios.data}
            selectedId={active}
            onSelect={setScenario}
          />
        ) : (
          <p className="text-[14px] text-lo">Loading incidents…</p>
        )}
      </aside>

      <div className="flex-1 min-w-0 overflow-y-auto p-5">
        <header className="mb-5">
          <h1 className="font-display text-lg text-hi tracking-display">
            Rings found in this incident
          </h1>
          <p className="text-[15px] text-lo mt-1.5 max-w-3xl leading-relaxed">
            Communities recovered by Louvain over the accounts the detector
            flagged, on a graph that combines transfer volume with shared-device
            and shared-IP links. Nothing below uses the generator&rsquo;s
            labels; the true rings are listed at the bottom for comparison.
          </p>
        </header>

        {discovered.isPending && (
          <p className="flex items-center gap-2 text-[15.5px] text-lo">
            <Loader2 size={14} className="animate-spin" aria-hidden />
            Clustering…
          </p>
        )}

        {discovered.error && (
          <p className="text-[15.5px] text-lo">
            {(discovered.error as Error).message}
          </p>
        )}

        {discovered.data && discovered.data.length === 0 && (
          <p className="text-[15.5px] text-lo max-w-xl leading-relaxed">
            No community in this incident is large enough to call a ring. Try an
            incident with a longer complaint delay, where more of the structure
            has had time to appear.
          </p>
        )}

        {discovered.data && discovered.data.length > 0 && (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-3">
            {discovered.data.map((ring) => (
              <RingCard key={ring.ring_id} ring={ring} />
            ))}
          </div>
        )}

        {truth.data && (
          <section className="mt-8 pt-5 border-t border-ink-line">
            <h2 className="font-display text-[17.5px] text-hi tracking-display">
              Ground truth: what the generator actually injected
            </h2>
            <p className="text-[14px] text-lo mt-1.5 mb-4 max-w-3xl leading-relaxed">
              Twelve rings across four typologies. Shown so the discovery above
              can be checked rather than taken on trust.
            </p>

            <div className="overflow-x-auto">
              <table className="w-full text-[14px] border-collapse min-w-[700px]">
                <thead>
                  <tr className="text-lo text-left">
                    <th className="font-normal py-2 pr-4">Ring</th>
                    <th className="font-normal py-2 px-3">Typology</th>
                    <th className="font-normal py-2 px-3 text-right">Accounts</th>
                    <th className="font-normal py-2 px-3 text-right">Banks</th>
                    <th className="font-normal py-2 px-3 text-right">Devices</th>
                    <th className="font-normal py-2 px-3 text-right">Layers</th>
                    <th className="font-normal py-2 px-3 text-right">Cash-out</th>
                    <th className="font-normal py-2 pl-3 text-right">Moved</th>
                  </tr>
                </thead>
                <tbody>
                  {truth.data.map((ring) => (
                    <tr key={ring.ring_id} className="border-t border-ink-line">
                      <td className="py-2 pr-4 font-mono text-hi">
                        {ring.ring_id}
                      </td>
                      <td className="py-2 px-3 text-lo">
                        {typologyLabel(ring.typology)}
                      </td>
                      <td className="py-2 px-3 text-right font-mono text-hi tabular-nums">
                        {ring.accounts}
                      </td>
                      <td className="py-2 px-3 text-right font-mono text-lo tabular-nums">
                        {ring.banks.length}
                      </td>
                      <td className="py-2 px-3 text-right font-mono text-lo tabular-nums">
                        {ring.device_clusters}
                      </td>
                      <td className="py-2 px-3 text-right font-mono text-lo tabular-nums">
                        {ring.max_layer}
                      </td>
                      <td className="py-2 px-3 text-right font-mono text-lo tabular-nums">
                        {ring.cashout_nodes}
                      </td>
                      <td className="py-2 pl-3 text-right font-mono text-flow tabular-nums">
                        {rupeesCompact(ring.total_flow_inr)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-[13px] text-lo/70 mt-3">
              {count(truth.data.reduce((sum, r) => sum + r.accounts, 0))} mule
              accounts in total.
            </p>
          </section>
        )}
      </div>
    </div>
  )
}
