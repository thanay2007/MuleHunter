import { institution } from '@/theme/tokens'

/**
 * A neutral geometric crest, drawn here rather than borrowed.
 *
 * DELIBERATELY NOT THE STATE EMBLEM AND NOT THE RBI MARK. Using either would
 * be impersonating a regulator to win a demo, and the honesty statement in the
 * README is one of this project's strongest assets -- spending it on a logo
 * would be a terrible trade. "What a Cyber Fraud Mitigation Centre console
 * would look like" is a stronger claim than pretending to be one, and it is
 * the claim every surface here makes.
 *
 * The shape is a chakra reading: a shield outline, a hub, and spokes. Line-art
 * in steel so it belongs to the chrome and never competes with the canvas.
 */
export default function Crest({ size = 24 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={institution.onNavy}
      strokeWidth={1.1}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable="false"
    >
      {/* Shield */}
      <path d="M12 1.6 21 4.6v7.2c0 4.6-3.6 8.6-9 10.6-5.4-2-9-6-9-10.6V4.6Z" />
      {/* Hub and spokes -- eight, evenly placed. */}
      <circle cx="12" cy="11.4" r="4.6" stroke={institution.steel} />
      <circle cx="12" cy="11.4" r="1.15" />
      {Array.from({ length: 8 }, (_, index) => {
        const angle = (index * Math.PI) / 4
        const inner = 1.9
        const outer = 4.6
        return (
          <line
            key={index}
            x1={12 + Math.cos(angle) * inner}
            y1={11.4 + Math.sin(angle) * inner}
            x2={12 + Math.cos(angle) * outer}
            y2={11.4 + Math.sin(angle) * outer}
            stroke={institution.steel}
          />
        )
      })}
    </svg>
  )
}
