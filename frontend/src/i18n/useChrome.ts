import { STRINGS, type ChromeStrings } from '@/i18n/strings'
import { useConsole } from '@/store/console'

/** The chrome strings for the currently selected language. */
export function useChrome(): ChromeStrings {
  return STRINGS[useConsole((s) => s.language)]
}
