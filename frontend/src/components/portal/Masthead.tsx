import { useEffect, useState } from 'react'
import Crest from '@/components/portal/Crest'
import { LANGUAGE_LABEL, type Language } from '@/i18n/strings'
import { useChrome } from '@/i18n/useChrome'
import { OPERATOR } from '@/lib/session'
import { useConsole } from '@/store/console'

/**
 * The masthead: which desk this is, who is sitting at it, and what time it is
 * there.
 *
 * Sits above the existing console header rather than replacing it. The frame
 * says "government fraud-mitigation portal"; everything below the frame is
 * untouched. Navy, steel and white only -- amber, teal and crimson belong to
 * money and never appear up here.
 */

/**
 * IST, live, seconds included.
 *
 * Its own component so the tick re-renders eight characters rather than the
 * whole masthead. The timezone is pinned rather than taken from the browser:
 * this desk is in India whatever laptop is driving the projector, and a demo
 * that shows the presenter's local time in a room full of Indian bankers reads
 * as a system that was never really about India.
 */
function SessionClock() {
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1_000)
    return () => window.clearInterval(timer)
  }, [])

  const time = now.toLocaleTimeString('en-GB', {
    timeZone: 'Asia/Kolkata',
    hour12: false,
  })

  return (
    <span className="font-mono text-[12px] text-institution-lo tabular-nums">
      {time} IST
    </span>
  )
}

function LanguageToggle() {
  const language = useConsole((s) => s.language)
  const setLanguage = useConsole((s) => s.setLanguage)
  const options: Language[] = ['en', 'hi']

  return (
    <div
      className="flex items-center gap-1 text-[12px]"
      role="group"
      aria-label="Language"
    >
      {options.map((option, index) => (
        <span key={option} className="flex items-center gap-1">
          {index > 0 && (
            <span className="text-institution-steel" aria-hidden>
              |
            </span>
          )}
          <button
            type="button"
            onClick={() => setLanguage(option)}
            aria-pressed={language === option}
            className={
              language === option
                ? 'text-institution-on'
                : 'text-institution-lo hover:text-institution-on transition-colors'
            }
          >
            {LANGUAGE_LABEL[option]}
          </button>
        </span>
      ))}
    </div>
  )
}

export default function Masthead() {
  const t = useChrome()

  return (
    <header className="shrink-0 h-16 bg-institution-navy border-b border-institution-rule flex items-center justify-between gap-4 px-5">
      <div className="flex items-center gap-3 min-w-0">
        <Crest size={24} />
        <div className="min-w-0">
          {/* Devanagari over English, the way a bilingual government lockup
              actually sets it -- and it stays that way in both languages, so
              the toggle changes the interface without restaging the identity. */}
          <div className="text-[13px] leading-tight text-institution-on truncate">
            साइबर वित्तीय धोखाधड़ी शमन केंद्र
          </div>
          <div className="text-[13px] leading-tight text-institution-on truncate">
            Cyber Financial Fraud Mitigation Centre
          </div>
          <div className="text-[11px] leading-tight text-institution-lo truncate mt-0.5">
            {t.consoleName}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-4 shrink-0">
        <div className="flex items-center gap-2.5">
          <span
            className="w-7 h-7 rounded-full border border-institution-steel flex items-center justify-center text-[12px] text-institution-on"
            aria-hidden
          >
            {OPERATOR.initial}
          </span>
          <span className="hidden md:block leading-tight">
            <span className="block text-[12.5px] text-institution-on">
              Officer {OPERATOR.id} · {t.officerDesk}
            </span>
            <SessionClock />
          </span>
        </div>
        <LanguageToggle />
      </div>
    </header>
  )
}
