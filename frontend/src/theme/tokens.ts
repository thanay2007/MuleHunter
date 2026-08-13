/**
 * Chakravyuh design tokens -- the ledger console.
 *
 * Concept: a night-shift financial crimes operations room. The chrome is deep,
 * cold and quiet. Every panel that holds *money* is inset in warm ledger paper,
 * the colour of a bank passbook. Rupees live on paper; the network lives in the
 * dark.
 *
 * COLOUR IS SEMANTIC AND THE RULE IS STRICT:
 *     amber   = money at risk / in motion
 *     teal    = money saved / freeze frontier
 *     crimson = money lost / cash-out
 * Nothing else on the page may be amber, teal or crimson. Not a hover state,
 * not a border, not an icon. If you reach for one of these three for
 * decoration, you have broken the language the judge is reading.
 */

export const tokens = {
  ink: '#0D1319', // base canvas
  inkRaised: '#141C25', // panels, cards
  inkLine: '#223140', // hairline borders -- 1px, never 2px
  paper: '#E9E3D4', // ledger inset background
  paperLine: '#CFC6B0', // ruled lines on paper insets
  flow: '#E0A03C', // money in motion (amber)
  interdict: '#2FBFB8', // freeze frontier, recovered funds (cold teal)
  burn: '#C8443E', // cash-out, leaked funds (crimson)
  textHi: '#EEF2F6',
  textLo: '#8A9AAA',
  textPaper: '#2A2620', // text on ledger insets
} as const

export type TokenName = keyof typeof tokens

/** Semantic aliases. Prefer these at call sites so intent survives refactors. */
export const semantic = {
  moneyAtRisk: tokens.flow,
  moneySaved: tokens.interdict,
  moneyLost: tokens.burn,
} as const

/** Motion durations in ms. The frontier sweep is the signature moment. */
export const motion = {
  graphLoadStagger: 600,
  frontierSweep: 900,
  counterRamp: 800,
  drawerSlide: 200,
  replayFps: 12,
} as const
