import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { api } from '@/api/client'
import {
  DelayCurve,
  InnocenceCurve,
  PolicyTable,
  RecoveryHistogram,
  StatTile,
} from '@/components/eval/BenchmarkPanel'
import { count, percent, rupeesCompact } from '@/lib/format'

/**
 * The Evaluation tab: every number a judge might challenge, in one place.
 *
 * It reads `data/benchmark.json` and `data/detector_report.json` and renders
 * them directly. Both are produced by explicit commands and neither is
 * generated on request, so what is on screen is always a run someone can
 * reproduce.
 */

function Missing({ message }: { message: string }) {
  return (
    <div className="panel p-6 max-w-xl">
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle size={16} className="text-hi" aria-hidden />
        <h2 className="font-display text-base text-hi tracking-display">
          Not generated yet
        </h2>
      </div>
      <p className="text-[13px] text-lo leading-relaxed">{message}</p>
    </div>
  )
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <section className="panel p-5">
      <div className="mb-4">
        <h2 className="font-display text-[15px] text-hi tracking-display">
          {title}
        </h2>
        {subtitle && (
          <p className="text-[11.5px] text-lo mt-1 leading-relaxed max-w-2xl">
            {subtitle}
          </p>
        )}
      </div>
      {children}
    </section>
  )
}

export default function Evaluation() {
  const benchmark = useQuery({ queryKey: ['benchmark'], queryFn: api.benchmark })
  const detector = useQuery({ queryKey: ['detector'], queryFn: api.detector })

  if (benchmark.isPending) {
    return (
      <div className="h-full flex items-center justify-center">
        <span className="flex items-center gap-2 text-[13px] text-lo">
          <Loader2 size={14} className="animate-spin" aria-hidden />
          Loading the benchmark…
        </span>
      </div>
    )
  }

  if (benchmark.error) {
    return (
      <div className="p-6">
        <Missing message={(benchmark.error as Error).message} />
      </div>
    )
  }

  const data = benchmark.data!
  const ours = data.policies.find((p) => p.policy === 'chakravyuh_greedy')
  const baseline = data.policies.find((p) => p.policy === 'named_account_only')
  const topk = data.policies.find((p) => p.policy === 'top_k_classifier')
  const adaptiveOurs = data.policies_adaptive_adversary.find(
    (p) => p.policy === 'chakravyuh_greedy',
  )
  const gap = data.optimality_gap

  const vsBaseline =
    ours && baseline && baseline.recovery_rate_mean > 0
      ? ours.recovery_rate_mean / baseline.recovery_rate_mean
      : null
  const vsTopK =
    ours && topk && topk.recovery_rate_mean > 0
      ? ours.recovery_rate_mean / topk.recovery_rate_mean
      : null

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6 space-y-5 max-w-[1400px]">
        <header>
          <h1 className="font-display text-[19px] text-hi tracking-display">
            Evaluation
          </h1>
          <p className="text-[12.5px] text-lo mt-1.5 leading-relaxed max-w-3xl">
            {count(data.n_incidents)} incidents, drawn only from rings held out
            of detector training ({data.holdout_rings.join(', ')}). Freeze
            authority K&nbsp;=&nbsp;{data.budget_k}, innocence budget
            B&nbsp;=&nbsp;{data.innocence_budget}. Every policy is planned from
            identical inputs and scored by replaying the same recorded timeline,
            so the comparison is like for like.
          </p>
        </header>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile
            label="Recovery rate, Chakravyuh"
            value={ours ? percent(ours.recovery_rate_mean) : '—'}
            hint={
              vsBaseline
                ? `${vsBaseline.toFixed(1)}× current practice`
                : 'current practice recovers nothing on these incidents'
            }
            tone="saved"
          />
          <StatTile
            label="Recovery rate, current practice"
            value={baseline ? percent(baseline.recovery_rate_mean) : '—'}
            hint="freeze the account named in the complaint"
          />
          <StatTile
            label="Innocent accounts frozen"
            value={ours ? count(ours.innocent_frozen_total) : '—'}
            hint={
              ours
                ? `${percent(ours.innocent_frozen_rate, 1)} of all freezes, over ${count(data.n_incidents)} incidents`
                : undefined
            }
            tone={ours && ours.innocent_frozen_total > 0 ? 'lost' : 'plain'}
          />
          <StatTile
            label="Solver latency, p95"
            value={ours ? `${ours.solve_ms_p95.toFixed(0)} ms` : '—'}
            hint={ours ? `p50 ${ours.solve_ms_p50.toFixed(0)} ms` : undefined}
          />
        </div>

        <Panel
          title="All four policies"
          subtitle="Recovery is rupees kept inside the banking system that would otherwise have been cashed out, measured against a do-nothing replay of the same incident. It is a counterfactual, so it cannot be inflated by freezing accounts that were never going to move."
        >
          <PolicyTable policies={data.policies} labels={data.policy_labels} />
          {vsTopK && (
            <p className="text-[11.5px] text-lo mt-3 leading-relaxed">
              Chakravyuh recovers{' '}
              <span className="font-mono text-hi">{vsTopK.toFixed(1)}×</span> what
              a top-K classifier recovers at the same freeze budget
              {ours && topk && ours.innocent_frozen_total <= topk.innocent_frozen_total
                ? ', while freezing no more innocent accounts.'
                : '.'}{' '}
              Detection is an input here, not the answer — both policies use the
              same scores.
            </p>
          )}
        </Panel>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
          <Panel
            title="What the golden hour is worth"
            subtitle="The same episodes, replayed at ten different complaint delays. Only the delay changes, so the curve isolates the single most important variable in the outcome."
          >
            <DelayCurve data={data.recovery_vs_delay} />
          </Panel>

          <Panel
            title="Tightening the innocence budget"
            subtitle="As B falls the solver spends less priced harm: it issues fewer freezes and switches to outbound holds and step-up verification. This is what 'what if the classifier is wrong' costs in rupees."
          >
            <InnocenceCurve data={data.innocence_sweep} />
          </Panel>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
          <Panel
            title="Recovery is not uniform"
            subtitle="Distribution across incidents. Some are hopeless — reported six hours late, money long gone — and the mean alone would hide that."
          >
            {ours && <RecoveryHistogram policy={ours} />}
          </Panel>

          <Panel
            title="How good is greedy, really?"
            subtitle="Interdiction over the sampled rollouts is weighted maximum coverage, which is monotone submodular — so greedy is guaranteed to reach (1 − 1/e) ≈ 63% of the optimum. That is the worst case. This is the measured one."
          >
            {gap.n_incidents > 0 ? (
              <div className="space-y-3">
                <div className="grid grid-cols-3 gap-3">
                  <StatTile
                    label="Mean gap vs CP-SAT"
                    value={percent(gap.mean_gap ?? 0, 2)}
                    tone="saved"
                  />
                  <StatTile
                    label="Worst gap observed"
                    value={percent(gap.max_gap ?? 0, 2)}
                  />
                  <StatTile
                    label="Worst case allowed by the bound"
                    value={percent(1 - (gap.theoretical_bound ?? 0.632), 1)}
                  />
                </div>
                <p className="text-[11.5px] text-lo leading-relaxed">
                  Solved exactly on {count(gap.n_incidents)} incidents small
                  enough for CP-SAT (median{' '}
                  {(gap.cpsat_ms_median ?? 0).toFixed(0)} ms). Both solvers
                  optimise an identical deterministic objective, so the gap
                  measures the search rather than the modelling.
                </p>
              </div>
            ) : (
              <p className="text-[12px] text-lo leading-relaxed">
                {gap.note ?? 'No incidents were small enough to solve exactly.'}
              </p>
            )}
          </Panel>
        </div>

        <Panel
          title="What if the syndicate adapts?"
          subtitle={`Every incident rerun against an operator who reroutes blocked money to another account they control, with probability ${percent(data.adversary_reroute_prob, 0)}, rather than giving up. Reported next to the passive figure rather than instead of it.`}
        >
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatTile
              label="Passive adversary"
              value={ours ? percent(ours.recovery_rate_mean) : '—'}
              tone="saved"
            />
            <StatTile
              label="Adaptive adversary"
              value={adaptiveOurs ? percent(adaptiveOurs.recovery_rate_mean) : '—'}
              hint={
                ours && adaptiveOurs
                  ? `${percent(
                      Math.max(
                        0,
                        1 -
                          adaptiveOurs.recovery_rate_mean /
                            Math.max(ours.recovery_rate_mean, 1e-9),
                      ),
                      0,
                    )} worse`
                  : undefined
              }
              tone="saved"
            />
            <StatTile
              label="Still kept in system"
              value={
                adaptiveOurs
                  ? rupeesCompact(adaptiveOurs.prevented_inr_total)
                  : '—'
              }
            />
            <StatTile
              label="Lost anyway"
              value={
                adaptiveOurs ? rupeesCompact(adaptiveOurs.leaked_inr_total) : '—'
              }
              tone="lost"
            />
          </div>
        </Panel>

        {detector.data && (
          <Panel
            title="Detection tiers"
            subtitle={`Rules, gradient boosting and a graph network, all trained on identical data and scored on identical held-out incidents (${detector.data.holdout_rings.join(', ')}). Detection feeds the solver; it is not the product.`}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-[12px] border-collapse min-w-[640px]">
                <thead>
                  <tr className="text-lo text-left">
                    <th className="font-normal py-2 pr-4">Tier</th>
                    <th className="font-normal py-2 px-3 text-right">AUC-PR</th>
                    <th className="font-normal py-2 px-3 text-right">P@100</th>
                    <th className="font-normal py-2 px-3 text-right">Precision</th>
                    <th className="font-normal py-2 px-3 text-right">Recall</th>
                    <th className="font-normal py-2 pl-3 text-right">Flagged</th>
                  </tr>
                </thead>
                <tbody>
                  {detector.data.tiers.map((tier) => (
                    <tr key={tier.tier} className="border-t border-ink-line">
                      <td className="py-2.5 pr-4 text-hi">{tier.tier}</td>
                      <td className="py-2.5 px-3 text-right font-mono text-hi tabular-nums">
                        {tier.auc_pr.toFixed(3)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-lo tabular-nums">
                        {tier.precision_at_100.toFixed(2)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-lo tabular-nums">
                        {tier.precision.toFixed(3)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-lo tabular-nums">
                        {tier.recall.toFixed(3)}
                      </td>
                      <td className="py-2.5 pl-3 text-right font-mono text-lo tabular-nums">
                        {count(tier.flagged)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="text-[11.5px] text-lo mt-3 leading-relaxed max-w-3xl">
              The rules tier flags {count(detector.data.tiers[0]?.flagged ?? 0)}{' '}
              accounts at{' '}
              {((detector.data.tiers[0]?.precision ?? 0) * 100).toFixed(0)}%
              precision — mostly legitimate high-velocity accounts, chit fund
              operators and travel agents who move money in and out within
              minutes. That failure is not fixable by moving a threshold. Ring
              discovery scores ARI{' '}
              <span className="font-mono text-hi">
                {detector.data.rings.ari.toFixed(3)}
              </span>{' '}
              against ground truth.
            </p>
            <p className="text-[11.5px] text-lo mt-2 leading-relaxed max-w-3xl">
              Note the scores are high because the task is heavily conditioned:
              these accounts are already known to have received money traced
              from a live fraud complaint minutes earlier. This is a much easier
              problem than unconditioned mule detection, and the figures should
              not be read as comparable to a standing detection system.
            </p>
          </Panel>
        )}

        <p className="text-[11px] text-lo/70 pb-4">
          Benchmark generated in {data.generated_seconds.toFixed(0)}s. Regenerate
          with <span className="font-mono">python -m app.eval.harness</span>.
        </p>
      </div>
    </div>
  )
}
