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

/**
 * How the console divides its space between the network and the money.
 *
 *   stacked  ledger across the bottom, canvas above it
 *   side     ledger docked to the right, canvas takes the rest of the width
 *   focus    ledger collapsed to a single summary line, canvas takes the room
 *
 * Worth having as a real control rather than a fixed layout: while an incident
 * is replaying you want the graph as large as it will go, and at the end you
 * want the two columns of figures. Those are different screens.
 */
export type ConsoleLayout = 'stacked' | 'side' | 'focus'

interface ConsoleState {
  scenarioId: string | null
  policy: PolicyId
  budgetK: number
  innocenceBudget: number
  adaptiveAdversary: boolean
  selectedNode: GraphNode | null
  phase: RunPhase
  layout: ConsoleLayout
  /** Height of the ledger band in `stacked`, in px. */
  ledgerHeight: number
  /** Width of the ledger dock in `side`, in px. */
  ledgerWidth: number

  setScenario: (id: string) => void
  setPolicy: (policy: PolicyId) => void
  setBudgetK: (k: number) => void
  setInnocenceBudget: (b: number) => void
  setAdaptiveAdversary: (on: boolean) => void
  selectNode: (node: GraphNode | null) => void
  setPhase: (phase: RunPhase) => void
  setLayout: (layout: ConsoleLayout) => void
  setLedgerHeight: (height: number) => void
  setLedgerWidth: (width: number) => void
  reset: () => void
}

/**
 * Default ledger band height. The panel's natural height is well over 500px,
 * and letting it size itself squeezed the graph into a strip -- so the band is
 * given a fixed share and scrolls internally, and the divider above it drags.
 */
export const DEFAULT_LEDGER_HEIGHT = 330
export const DEFAULT_LEDGER_WIDTH = 430

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
  layout: 'stacked',
  ledgerHeight: DEFAULT_LEDGER_HEIGHT,
  ledgerWidth: DEFAULT_LEDGER_WIDTH,

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
  // Layout is a view preference, so it deliberately does not reset the phase
  // the way the budgets do -- rearranging the screen must never discard a plan.
  setLayout: (layout) => set({ layout }),
  setLedgerHeight: (ledgerHeight) => set({ ledgerHeight }),
  setLedgerWidth: (ledgerWidth) => set({ ledgerWidth }),
  reset: () => set({ selectedNode: null, phase: 'idle' }),
}))
