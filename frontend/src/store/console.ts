import { create } from 'zustand'
import type { GraphNode, PolicyId } from '@/api/client'

/**
 * Console state.
 *
 * Deliberately small. The replay timeline is *not* here -- it lives in the
 * WebSocket hook, because it arrives from the server sixty times a second and
 * pushing it through a global store would re-render the whole console on every
 * frame. What lives here is what the user chose.
 */

export type RunPhase = 'idle' | 'planning' | 'running' | 'done'

interface ConsoleState {
  scenarioId: string | null
  policy: PolicyId
  budgetK: number
  innocenceBudget: number
  adaptiveAdversary: boolean
  selectedNode: GraphNode | null
  phase: RunPhase

  setScenario: (id: string) => void
  setPolicy: (policy: PolicyId) => void
  setBudgetK: (k: number) => void
  setInnocenceBudget: (b: number) => void
  setAdaptiveAdversary: (on: boolean) => void
  selectNode: (node: GraphNode | null) => void
  setPhase: (phase: RunPhase) => void
  reset: () => void
}

/** Matches `settings.default_budget_k` / `default_innocence_budget`. */
export const DEFAULT_BUDGET_K = 25
export const DEFAULT_INNOCENCE_BUDGET = 2.0

export const useConsole = create<ConsoleState>((set) => ({
  scenarioId: null,
  policy: 'chakravyuh_greedy',
  budgetK: DEFAULT_BUDGET_K,
  innocenceBudget: DEFAULT_INNOCENCE_BUDGET,
  adaptiveAdversary: false,
  selectedNode: null,
  phase: 'idle',

  setScenario: (id) =>
    set({ scenarioId: id, selectedNode: null, phase: 'idle' }),
  setPolicy: (policy) => set({ policy, phase: 'idle' }),
  // Changing a budget invalidates the plan on screen, so the phase resets and
  // the console asks to be run again rather than showing a plan that no longer
  // corresponds to the controls above it.
  setBudgetK: (budgetK) => set({ budgetK, phase: 'idle' }),
  setInnocenceBudget: (innocenceBudget) => set({ innocenceBudget, phase: 'idle' }),
  setAdaptiveAdversary: (adaptiveAdversary) =>
    set({ adaptiveAdversary, phase: 'idle' }),
  selectNode: (selectedNode) => set({ selectedNode }),
  setPhase: (phase) => set({ phase }),
  reset: () => set({ selectedNode: null, phase: 'idle' }),
}))
