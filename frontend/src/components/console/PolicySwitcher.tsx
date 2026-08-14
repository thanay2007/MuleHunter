import type { PolicyId } from '@/api/client'
import { useConsole } from '@/store/console'

/**
 * Which policy plans this case.
 *
 * The backend has had all four since phase 4 and the store has had `policy`
 * since phase 5, but nothing ever rendered it -- so the strongest argument in
 * the project was only visible as a static table on another tab.
 *
 * Switching re-plans and re-replays the case in front of the judge, from the
 * same detector scores. That is the whole thesis in one control: top-K spends
 * every one of its 25 freezes and still loses more money, because detection is
 * an input to this problem and not the answer to it.
 */

const POLICIES: { id: PolicyId; label: string }[] = [
  { id: 'named_account_only', label: 'Current practice' },
  { id: 'one_hop_downstream', label: 'One hop' },
  { id: 'top_k_classifier', label: 'Top-K classifier' },
  { id: 'chakravyuh_greedy', label: 'Chakravyuh' },
]

export default function PolicySwitcher() {
  const policy = useConsole((s) => s.policy)
  const setPolicy = useConsole((s) => s.setPolicy)

  return (
    <div
      className="grid grid-cols-2 gap-1"
      role="group"
      aria-label="Planning policy"
    >
      {POLICIES.map((option) => {
        const active = option.id === policy
        return (
          <button
            key={option.id}
            type="button"
            onClick={() => setPolicy(option.id)}
            aria-pressed={active}
            className={[
              'px-2 py-1 rounded-panel border text-[12.5px] text-left transition-colors',
              active
                ? 'border-hi/40 text-hi bg-ink-raised'
                : 'border-ink-line text-lo hover:text-hi',
            ].join(' ')}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
