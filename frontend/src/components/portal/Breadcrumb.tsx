import { ChevronRight } from 'lucide-react'
import { institution } from '@/theme/tokens'

/**
 * Where you are in the portal. Steel separators, last crumb in `onNavy`.
 *
 * Twenty-two pixels, so it stays inside the 140px the whole frame is allowed.
 */
export default function Breadcrumb({ trail }: { trail: string[] }) {
  return (
    <nav
      className="shrink-0 h-[22px] bg-institution-navy border-b border-institution-rule flex items-center gap-1.5 px-5 overflow-hidden"
      aria-label="Breadcrumb"
    >
      {trail.map((crumb, index) => {
        const last = index === trail.length - 1
        return (
          <span key={`${crumb}-${index}`} className="flex items-center gap-1.5 min-w-0">
            {index > 0 && (
              <ChevronRight
                size={11}
                color={institution.steel}
                aria-hidden
                className="shrink-0"
              />
            )}
            <span
              className={[
                'text-[11.5px] truncate',
                last ? 'text-institution-on' : 'text-institution-lo',
              ].join(' ')}
              aria-current={last ? 'page' : undefined}
            >
              {crumb}
            </span>
          </span>
        )
      })}
    </nav>
  )
}
