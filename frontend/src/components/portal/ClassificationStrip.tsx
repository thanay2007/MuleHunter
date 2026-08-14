import { useChrome } from '@/i18n/useChrome'

/**
 * The classification bar.
 *
 * Twenty-two pixels that do more for perceived seriousness than anything else
 * in the frame -- because every operational system anybody has worked on has
 * one, and none of them are decorative. It also carries the two words that
 * keep this honest, SYNTHETIC DATA and PROTOTYPE, in the one place on the
 * screen a reader cannot scroll past.
 */
export default function ClassificationStrip() {
  const t = useChrome()
  return (
    <div className="shrink-0 h-[22px] bg-institution-deep flex items-center justify-center">
      <span className="text-[11px] uppercase tracking-[0.16em] text-institution-lo text-center px-3 truncate">
        {t.classification}
      </span>
    </div>
  )
}
