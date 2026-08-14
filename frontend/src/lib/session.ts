/**
 * Who is at the desk, and which sitting this is.
 *
 * The operator identity is demo content, not a tunable -- there is no auth in
 * this project and there deliberately never will be ("two commands, no keys,
 * runs air-gapped" is a selling point to anyone who has worked in a bank). It
 * lives here so the masthead, the audit trail and the freeze order all name the
 * same officer instead of three hardcoded strings drifting apart.
 */
export const OPERATOR = {
  id: 'SO-441',
  /** Initial for the avatar chip. */
  initial: 'S',
} as const

/**
 * Identifies this browser sitting, for the footer and the audit log.
 *
 * Random on purpose, and deliberately NOT used in any issued document: a
 * session id is the one thing here that *should* differ between runs, whereas
 * a freeze order has to be byte-identical for identical inputs. The order
 * carries its own audit reference, derived from the case in `references.py`.
 */
export const SESSION_ID: string = crypto.randomUUID()

/** Short form for chrome, where the full UUID would not fit. */
export const SESSION_ID_SHORT: string = SESSION_ID.slice(0, 8)
