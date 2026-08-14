import { create } from 'zustand'
import type { GraphNode, PolicyId, Scenario } from '@/api/client'
import type { Language } from '@/i18n/strings'

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
  /** Chrome language. The operations canvas stays in English either way. */
  language: Language
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
  /**
   * Recovery share from the most recent *passive* run, keyed by case and
   * settings. The adaptive-adversary caption reports `38% → 29%`, and the
   * left-hand figure has to come from somewhere honest: this is the number
   * this console actually produced for the same case under the same budgets,
   * not a constant copied out of the README. Solving the passive case a second
   * time purely to draw a caption would double every solve on stage.
   */
  passiveRecovery: Record<string, number>
  /**
   * The last result from each policy, per case. Keyed `scenario|policy`.
   *
   * This is what turns the policy switcher into an argument rather than a
   * setting: after four runs the judge is looking at a live head-to-head on
   * the incident in front of them, produced by this console during the demo,
   * instead of a static table on another tab.
   */
  policyRuns: Record<string, PolicyRun>
  /**
   * Complaints filed through the intake form, shaped like scenarios so the
   * console can render one without a second code path. They are not persisted
   * anywhere -- this project has no database and deliberately never will.
   */
  filedIncidents: Scenario[]

  setScenario: (id: string) => void
  setPolicy: (policy: PolicyId) => void
  setLanguage: (language: Language) => void
  setBudgetK: (k: number) => void
  setInnocenceBudget: (b: number) => void
  setAdaptiveAdversary: (on: boolean) => void
  selectNode: (node: GraphNode | null) => void
  setPhase: (phase: RunPhase) => void
  setLayout: (layout: ConsoleLayout) => void
  setLedgerHeight: (height: number) => void
  setLedgerWidth: (width: number) => void
  rememberPassiveRecovery: (key: string, share: number) => void
  rememberPolicyRun: (scenarioId: string, run: PolicyRun) => void
  addFiledIncident: (incident: Scenario) => void
  reset: () => void
}

/** One policy's outcome on one case, as this console measured it. */
export interface PolicyRun {
  policy: PolicyId
  policyLabel: string
  /** Prevented rupees over rupees stolen -- the README's definition. */
  recoveryShare: number
  preventedInr: number
  innocentFrozen: number
  frozen: number
  budgetK: number
  innocenceBudget: number
  adaptiveAdversary: boolean
}

/**
 * Identifies a run for the passive-recovery memo. Every input that changes the
 * plan is in the key, so a remembered figure can never be shown next to a run
 * it did not come from.
 */
export function runKey(
  scenarioId: string,
  policy: PolicyId,
  budgetK: number,
  innocenceBudget: number,
): string {
  return `${scenarioId}|${policy}|${budgetK}|${innocenceBudget}`
}

/**
 * Default ledger band height. The panel's natural height is well over 500px,
 * and letting it size itself squeezed the graph into a strip -- so the band is
 * given a fixed share and scrolls internally, and the divider above it drags.
 */
export const DEFAULT_LEDGER_HEIGHT = 330
export const DEFAULT_LEDGER_WIDTH = 430

/** Matches `settings.default_budget_k`. */
export const DEFAULT_BUDGET_K = 25

/**
 * Where the harm-limit slider starts, which is deliberately *not*
 * `settings.default_innocence_budget` (2.0).
 *
 * 2.0 is the benchmark's budget and stays that way -- the published results
 * are quoted at it, and moving it would silently restate them. But at 2.0 the
 * solver already has all the authority it wants, so the console would open on
 * the flat part of the curve where dragging the slider does nothing. Starting
 * at the mixed regime means the first drag a judge sees changes the plan's
 * composition, which is the whole point of the control.
 */
export const DEFAULT_INNOCENCE_BUDGET = 0.25

export const useConsole = create<ConsoleState>((set) => ({
  scenarioId: null,
  policy: 'chakravyuh_greedy',
  language: 'en',
  budgetK: DEFAULT_BUDGET_K,
  innocenceBudget: DEFAULT_INNOCENCE_BUDGET,
  adaptiveAdversary: false,
  selectedNode: null,
  phase: 'idle',
  layout: 'stacked',
  ledgerHeight: DEFAULT_LEDGER_HEIGHT,
  ledgerWidth: DEFAULT_LEDGER_WIDTH,
  passiveRecovery: {},
  policyRuns: {},
  filedIncidents: [],

  setScenario: (id) =>
    set({ scenarioId: id, selectedNode: null, phase: 'idle' }),
  setPolicy: (policy) => set({ policy, phase: 'idle' }),
  // Language is chrome only, so it deliberately does not reset the phase --
  // switching it must never discard a plan.
  setLanguage: (language) => set({ language }),
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
  rememberPassiveRecovery: (key, share) =>
    set((state) => ({ passiveRecovery: { ...state.passiveRecovery, [key]: share } })),
  addFiledIncident: (incident) =>
    set((state) => ({
      filedIncidents: [
        ...state.filedIncidents.filter(
          (existing) => existing.scenario_id !== incident.scenario_id,
        ),
        incident,
      ],
    })),
  rememberPolicyRun: (scenarioId, run) =>
    set((state) => ({
      policyRuns: { ...state.policyRuns, [`${scenarioId}|${run.policy}`]: run },
    })),
  reset: () => set({ selectedNode: null, phase: 'idle' }),
}))
