import type { PolicyId } from '@/api/client'
import { count, percent, rupees } from '@/lib/format'
import { useConsole, type PolicyRun } from '@/store/console'

/**
 * The live head-to-head, built up during the demo.
 *
 * Every run leaves its result here, so after switching through the policies on
 * one case the judge is reading a comparison this console produced in front of
 * them rather than a table from the README. Same case, same detector scores,
 * same budgets — only the planner differs, which is exactly the comparison the
 * project is asking to be judged on.
 *
 * COLOUR: none of the three money colours appear here. This sits on the dark
 * canvas, where amber, teal and crimson mean flowing, frozen and gone; a
 * summary table borrowing them would put four more "money" signals on a screen
 * that already has them. The best row is marked by weight instead.
 */

const ORDER: PolicyId[] = [
  'named_account_only',
  'one_hop_downstream',
  'top_k_classifier',
  'chakravyuh_greedy',
]

export default function PolicyCompare({
  scenarioId,
  activePolicy,
}: {
  scenarioId: string | null
  activePolicy: PolicyId
}) {
  const policyRuns = useConsole((s) => s.policyRuns)

  if (!scenarioId) return null

  const runs: PolicyRun[] = ORDER.map(
    (policy) => policyRuns[`${scenarioId}|${policy}`],
  ).filter((run): run is PolicyRun => Boolean(run))

  if (runs.length < 2) {
    return (
      <div className="px-5 py-1.5 border-t border-ink-line">
        <p className="text-[12.5px] text-lo">
          {runs.length === 0
            ? 'Run the case to start the comparison.'
            : 'Switch policy and run again to compare them side by side on this case.'}
        </p>
      </div>
    )
  }

  const best = Math.max(...runs.map((run) => run.recoveryShare))

  return (
    <div className="px-5 py-1.5 border-t border-ink-line overflow-x-auto">
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="text-lo">
            {['Policy', 'Recovered', 'Kept', 'Frozen', 'Innocent'].map(
              (heading, index) => (
                <th
                  key={heading}
                  className={[
                    'font-normal text-[10px] tracking-[0.08em] uppercase pb-0.5',
                    index === 0 ? 'text-left' : 'text-right',
                  ].join(' ')}
                >
                  {heading}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const leading = run.recoveryShare >= best
            return (
              <tr
                key={run.policy}
                className={run.policy === activePolicy ? 'text-hi' : 'text-lo'}
              >
                <td className="py-0.5 whitespace-nowrap">
                  {run.policyLabel}
                  {run.adaptiveAdversary && (
                    <span className="text-lo/70"> · adaptive</span>
                  )}
                </td>
                <td
                  className={[
                    'py-0.5 text-right font-mono tabular-nums',
                    leading ? 'text-hi' : '',
                  ].join(' ')}
                >
                  {percent(run.recoveryShare, 1)}
                </td>
                <td className="py-0.5 text-right font-mono tabular-nums">
                  {rupees(run.preventedInr)}
                </td>
                <td className="py-0.5 text-right font-mono tabular-nums">
                  {count(run.frozen)}
                </td>
                <td className="py-0.5 text-right font-mono tabular-nums">
                  {count(run.innocentFrozen)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
