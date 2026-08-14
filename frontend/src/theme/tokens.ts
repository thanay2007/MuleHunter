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

/**
 * Institutional chrome. Masthead, classification strip, breadcrumb, footer.
 *
 * CHROME ONLY. None of these may appear on the operations canvas, and nothing
 * from the canvas may appear here. The frame and the working surface are two
 * different visual languages on purpose: the frame says which desk you are
 * sitting at, the canvas says where the money is.
 *
 * NO SAFFRON. The obvious instinct for a government look is #FF9933, and it is
 * a trap -- it sits a few degrees from `flow` (#E0A03C), which is reserved for
 * money at risk. A judge reading amber as "money in motion" everywhere else
 * would find it in the masthead and the whole colour language stops meaning
 * anything. Navy, steel, white and grey do the institutional job without
 * touching the three reserved hues.
 */
export const institution = {
  navy: '#0B2E4F', // masthead ground
  navyDeep: '#071F35', // classification strip
  steel: '#3E5C78', // secondary chrome, breadcrumb separators
  rule: '#1A3E5F', // hairline on navy -- 1px, never 2px
  onNavy: '#E8EEF4', // primary text on navy
  onNavyLo: '#93A9BF', // secondary text on navy
} as const

/**
 * Control geometry. Not colour, and deliberately not mirrored into Tailwind --
 * these are numbers the console's inputs need, kept here so no module carries
 * an unexplained constant.
 */
export const controls = {
  /**
   * Harm-limit slider travel.
   *
   * The plan saturates well below B = 1 on every seeded scenario -- past
   * `innocenceFullAuthority` the solver already buys every freeze it wants, so
   * more budget buys nothing. The old 0.05-8 range therefore spent 94% of its
   * pixels on a no-op, which is a poor advertisement for the one control that
   * answers "what if your classifier is wrong". Capping travel at 2.0 keeps a
   * visible margin above saturation without wasting the rail.
   */
  innocenceBudgetMin: 0.05,
  innocenceBudgetMax: 2.0,
  /**
   * Exponent of the position -> budget map, `B = min + (max - min) * t^curve`.
   *
   * Solved so that t = 0.70 lands exactly on B = 0.50: the interesting band
   * (gentle through full authority) gets 70% of the pixel width and the flat
   * tail gets the remaining 30%. The displayed value stays linear in B -- only
   * the travel is warped, so the number under the operator's finger is still
   * the number the solver receives.
   */
  innocenceBudgetCurve: 4.11,
  /** Regime boundaries, where the plan's *composition* changes on S1. */
  innocenceMixed: 0.25,
  innocenceFullAuthority: 0.5,
} as const

/** Motion durations in ms. The frontier sweep is the signature moment. */
export const motion = {
  graphLoadStagger: 600,
  frontierSweep: 900,
  counterRamp: 800,
  drawerSlide: 200,
  replayFps: 12,
} as const
