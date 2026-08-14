import type { Config } from 'tailwindcss'
import { tokens } from './src/theme/tokens'

/**
 * Mirrors src/theme/tokens.ts. Tokens are defined once there and imported here
 * so the two can never drift.
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: tokens.ink,
          raised: tokens.inkRaised,
          line: tokens.inkLine,
        },
        paper: {
          DEFAULT: tokens.paper,
          line: tokens.paperLine,
          text: tokens.textPaper,
        },
        flow: tokens.flow,
        interdict: tokens.interdict,
        burn: tokens.burn,
        hi: tokens.textHi,
        lo: tokens.textLo,
      },
      fontFamily: {
        display: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      letterSpacing: {
        display: '-0.02em',
      },
      borderRadius: {
        panel: '3px',
      },
    },
  },
  plugins: [],
} satisfies Config
