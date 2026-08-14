import { useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { Loader2, X } from 'lucide-react'
import { api, type AccountDetail } from '@/api/client'
import { archetypeLabel, elapsed, percent, rupees, rupeesCompact } from '@/lib/format'
import { tokens } from '@/theme/tokens'

/**
 * Why this account was frozen.
 *
 * Four questions, in the order a judge asks them:
 *   1. What is it, and how much of the victim's money touched it?
 *   2. What drove the score? (SHAP, phrased in English)
 *   3. How does it differ from an ordinary account? (diverging bars)
 *   4. What did freezing it save, and what would waiting have cost?
 *
 * The fourth is the one that lands. "Freezing this at T+44 saved ₹59,229;
 * at T+104 it would have saved ₹15,380" is a claim about this account in this
 * incident, and it is computed by re-running the cached rollouts with that one
 * freeze moved in time.
 */

const DRAWER_MS = 0.2

interface Props {
  accountId: string | null
  scenarioId: string | null
  budgetK: number
  innocenceBudget: number
  onClose: () => void
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 text-[12px]">
      <dt className="text-lo">{label}</dt>
      <dd className="font-mono text-hi text-right tabular-nums">{value}</dd>
    </div>
  )
}

function ShapBars({ detail }: { detail: AccountDetail }) {
  const peak = Math.max(...detail.attributions.map((a) => Math.abs(a.shap)), 1e-6)

  return (
    <ul className="space-y-2">
      {detail.attributions.map((a) => {
        const width = (Math.abs(a.shap) / peak) * 100
        const raises = a.direction === 'raises'
        return (
          <li key={a.feature}>
            <div className="flex items-baseline justify-between gap-2 mb-1">
              <span className="text-[11.5px] text-hi leading-snug">{a.plain}</span>
              <span className="font-mono text-[10.5px] text-lo shrink-0 tabular-nums">
                {a.shap >= 0 ? '+' : ''}
                {a.shap.toFixed(2)}
              </span>
            </div>
            <div className="h-1 bg-ink rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${width}%`,
                  backgroundColor: raises ? tokens.textHi : tokens.textLo,
                  opacity: raises ? 0.85 : 0.4,
                }}
              />
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function FeatureDeviations({ detail }: { detail: AccountDetail }) {
  // Only the features that actually differ; a table of 36 rows mostly at zero
  // hides the handful that matter.
  const notable = [...detail.features]
    .filter((f) => Math.abs(f.deviation) > 0.5)
    .sort((a, b) => Math.abs(b.deviation) - Math.abs(a.deviation))
    .slice(0, 10)

  if (notable.length === 0) {
    return (
      <p className="text-[11.5px] text-lo leading-relaxed">
        This account sits close to the population median on every feature. That
        is exactly why a per-account rule engine cannot see it.
      </p>
    )
  }

  return (
    <ul className="space-y-1.5">
      {notable.map((f) => {
        const magnitude = Math.min(1, Math.abs(f.deviation) / 6)
        const above = f.deviation > 0
        return (
          <li key={f.feature} className="text-[11px]">
            <div className="flex justify-between gap-2 mb-0.5">
              <span className="text-lo truncate">{f.label}</span>
              <span className="font-mono text-hi shrink-0 tabular-nums">
                {f.value.toFixed(2)}
                <span className="text-lo"> / {f.population_median.toFixed(2)}</span>
              </span>
            </div>
            {/* Diverging bar: centre line is the population median. */}
            <div className="relative h-1 bg-ink rounded-full">
              <div className="absolute left-1/2 top-0 bottom-0 w-px bg-ink-line" />
              <div
                className="absolute top-0 bottom-0 rounded-full"
                style={{
                  left: above ? '50%' : `${50 - magnitude * 50}%`,
                  width: `${magnitude * 50}%`,
                  backgroundColor: tokens.textLo,
                  opacity: 0.75,
                }}
              />
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function MarginalRecovery({ detail }: { detail: AccountDetail }) {
  const { marginal } = detail

  if (marginal.saved_inr <= 0) {
    return (
      <p className="text-[11.5px] text-lo leading-relaxed">
        Freezing this account would not have saved anything: no forecast path of
        the victim&rsquo;s money runs through it after the complaint.
      </p>
    )
  }

  const later = marginal.alternatives.filter((a) => a.saved_inr < marginal.saved_inr)

  return (
    <div>
      <p className="text-[12px] text-hi leading-relaxed">
        Freezing this account at{' '}
        <span className="font-mono tabular-nums">
          {elapsed(marginal.issued_at_minute ?? 0)}
        </span>{' '}
        saved{' '}
        <span className="font-mono tabular-nums text-interdict">
          {rupees(marginal.saved_inr)}
        </span>
        .
      </p>

      {later.length > 0 && (
        <p className="text-[11.5px] text-lo leading-relaxed mt-2">
          Issued at{' '}
          <span className="font-mono tabular-nums">
            {elapsed(later[later.length - 1]!.minute)}
          </span>{' '}
          instead, it would have saved{' '}
          <span className="font-mono tabular-nums text-hi">
            {rupees(later[later.length - 1]!.saved_inr)}
          </span>
          .
        </p>
      )}

      <div className="mt-3 space-y-1">
        {[
          { minute: marginal.issued_at_minute ?? 0, saved_inr: marginal.saved_inr },
          ...marginal.alternatives,
        ].map((point) => {
          const share = marginal.saved_inr > 0 ? point.saved_inr / marginal.saved_inr : 0
          return (
            <div key={point.minute} className="flex items-center gap-2">
              <span className="font-mono text-[10.5px] text-lo w-12 shrink-0 tabular-nums">
                {elapsed(point.minute)}
              </span>
              <div className="flex-1 h-1.5 bg-ink rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.max(1, share * 100)}%`,
                    backgroundColor: tokens.interdict,
                    opacity: 0.35 + 0.65 * share,
                  }}
                />
              </div>
              <span className="font-mono text-[10.5px] text-hi w-16 text-right shrink-0 tabular-nums">
                {rupeesCompact(point.saved_inr)}
              </span>
            </div>
          )
        })}
      </div>
      <p className="text-[10.5px] text-lo mt-2 leading-snug">
        Recomputed by re-running the cached rollouts with this one freeze
        delayed, every other freeze held fixed.
      </p>
    </div>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="px-4 py-4 border-t border-ink-line">
      <h3 className="label-lo mb-2.5">{title}</h3>
      {children}
    </section>
  )
}

export default function AccountDrawer({
  accountId,
  scenarioId,
  budgetK,
  innocenceBudget,
  onClose,
}: Props) {
  const query = useQuery({
    queryKey: ['account', accountId, scenarioId, budgetK, innocenceBudget],
    queryFn: () =>
      api.account(accountId as string, scenarioId as string, budgetK, innocenceBudget),
    enabled: Boolean(accountId && scenarioId),
  })

  return (
    <AnimatePresence>
      {accountId && (
        <motion.aside
          initial={{ x: '100%' }}
          animate={{ x: 0 }}
          exit={{ x: '100%' }}
          transition={{ duration: DRAWER_MS, ease: 'easeOut' }}
          className="absolute top-0 right-0 bottom-0 w-[352px] bg-ink-raised border-l border-ink-line overflow-y-auto z-20"
          aria-label={`Account ${accountId}`}
        >
          <header className="sticky top-0 bg-ink-raised px-4 py-3 border-b border-ink-line flex items-start justify-between gap-3 z-10">
            <div className="min-w-0">
              <div className="font-mono text-[13px] text-hi truncate">
                {accountId}
              </div>
              {query.data && (
                <div className="text-[11px] text-lo mt-0.5 truncate">
                  {query.data.bank_id} · {query.data.district} ·{' '}
                  {archetypeLabel(query.data.archetype)}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close account details"
              className="text-lo hover:text-hi shrink-0 p-0.5 rounded"
            >
              <X size={15} aria-hidden />
            </button>
          </header>

          {query.isPending && (
            <div className="px-4 py-8 flex items-center gap-2 text-[12px] text-lo">
              <Loader2 size={13} className="animate-spin" aria-hidden />
              Working out why…
            </div>
          )}

          {query.error && (
            <div className="px-4 py-6">
              <p className="text-[12px] text-lo leading-relaxed">
                {(query.error as Error).message}
              </p>
            </div>
          )}

          {query.data && (
            <>
              <div className="px-4 py-4">
                <dl className="space-y-2">
                  <Row
                    label="Mule probability"
                    value={percent(query.data.p_mule, 1)}
                  />
                  <Row
                    label="Victim's money held here"
                    value={rupees(query.data.tainted_held_inr)}
                  />
                  <Row
                    label="Passed through"
                    value={rupees(query.data.tainted_through_inr)}
                  />
                  {query.data.first_seen_minute !== null && (
                    <Row
                      label="Money arrived"
                      value={elapsed(query.data.first_seen_minute)}
                    />
                  )}
                  <Row label="Opened" value={query.data.open_date} />
                  <Row label="KYC" value={query.data.kyc_tier} />
                </dl>
              </div>

              <Section title="What the freeze was worth">
                <MarginalRecovery detail={query.data} />
              </Section>

              <Section title="Why the model scored it this way">
                <ShapBars detail={query.data} />
              </Section>

              <Section title="How it differs from an ordinary account">
                <FeatureDeviations detail={query.data} />
              </Section>

              <Section title="What today's rule engine sees">
                {query.data.rule_flags.length > 0 ? (
                  <ul className="space-y-1">
                    {query.data.rule_flags.map((flag) => (
                      <li key={flag} className="font-mono text-[11px] text-hi">
                        {flag}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[11.5px] text-lo leading-relaxed">
                    Nothing. The rules baseline does not flag this account at
                    all &mdash; individually it is unremarkable, and only its
                    neighbourhood gives it away.
                  </p>
                )}
              </Section>

              <Section title="Ground truth">
                <dl className="space-y-2">
                  <Row
                    label="Actually a mule"
                    value={query.data.is_mule ? 'yes' : 'no'}
                  />
                  {query.data.ring_id && (
                    <Row label="Ring" value={query.data.ring_id} />
                  )}
                  {query.data.layer_index >= 0 && (
                    <Row
                      label="Layer in the chain"
                      value={String(query.data.layer_index)}
                    />
                  )}
                  <Row
                    label="Cash-out node"
                    value={query.data.is_cashout_node ? 'yes' : 'no'}
                  />
                </dl>
                <p className="text-[10.5px] text-lo mt-2.5 leading-snug">
                  Labels come from the generator and are shown so the freeze
                  list can be audited. Nothing above this line uses them.
                </p>
              </Section>
            </>
          )}
        </motion.aside>
      )}
    </AnimatePresence>
  )
}
