import { AlertTriangle, Loader2 } from 'lucide-react'
import { ApiError } from '@/api/client'

/**
 * What every route shows when it has nothing to draw.
 *
 * A demo dies on the screen that renders a raw stack trace or, worse, an empty
 * chart that looks like a real result of zero. Every failure here resolves to a
 * calm sentence plus the exact command that fixes it, and the three cases are
 * genuinely different problems:
 *
 *   backend unreachable   the server is not running
 *   503                   the server is running, the artifacts are not built
 *   anything else         say what the server said, and offer no false remedy
 *
 * Printing a "start the backend" block under a problem that is not the backend
 * teaches the reader to ignore the instructions on every other screen, so the
 * command is omitted when there is not one worth running.
 */

const START_BACKEND = 'cd backend\nuvicorn app.main:app --reload --port 8000'
const BUILD_ARTIFACTS =
  'cd backend\npython -m app.simulator.generator\npython -m app.detect.train'

export function RouteLoading({ label }: { label: string }) {
  return (
    <div className="h-full flex items-center justify-center">
      <span className="flex items-center gap-2 text-[15.5px] text-lo">
        <Loader2 size={14} className="animate-spin" aria-hidden />
        {label}
      </span>
    </div>
  )
}

export function RouteMessage({
  title,
  message,
  command,
}: {
  title: string
  message: string
  command?: string
}) {
  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="panel p-6 max-w-lg">
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle size={16} className="text-hi" aria-hidden />
          <h2 className="font-display text-base text-hi tracking-display">
            {title}
          </h2>
        </div>
        <p className="text-[15.5px] text-lo leading-relaxed">{message}</p>
        {command && (
          <pre className="mt-3 font-mono text-[14px] text-hi bg-ink p-3 rounded-panel border border-ink-line whitespace-pre-wrap">
            {command}
          </pre>
        )}
      </div>
    </div>
  )
}

/** Turns any query error into the right message and remedy. */
export function RouteError({
  error,
  /** What this route was trying to load, e.g. "the ring analysis". */
  subject,
}: {
  error: unknown
  subject: string
}) {
  const status = error instanceof ApiError ? error.status : undefined
  const message = (error as Error).message

  if (status === 0) {
    return (
      <RouteMessage
        title="Backend not running"
        message={`Could not reach the API, so ${subject} is unavailable. Start the backend and this page will load itself.`}
        command={START_BACKEND}
      />
    )
  }

  if (status === 503) {
    return (
      <RouteMessage
        title="Not generated yet"
        message={message}
        command={BUILD_ARTIFACTS}
      />
    )
  }

  return <RouteMessage title="Nothing to show" message={message} />
}
