import { useCallback, useRef } from 'react'

/**
 * A draggable divider between two panes.
 *
 * The ledger and the graph are both things you want more of at different
 * moments, and no fixed split serves both. Drag to rebalance.
 *
 * Keyboard-operable as well as draggable: it carries `role="separator"` with a
 * value, so arrow keys move it. A divider you can only reach with a mouse is
 * not a control, it is an obstacle.
 */

interface Props {
  orientation: 'horizontal' | 'vertical'
  /** Current size of the pane being resized, in px. */
  size: number
  onChange: (size: number) => void
  min: number
  max: number
  label: string
  /** Step used by the arrow keys. */
  step?: number
}

export default function Splitter({
  orientation,
  size,
  onChange,
  min,
  max,
  label,
  step = 24,
}: Props) {
  const start = useRef({ pointer: 0, size: 0 })

  const clamp = useCallback(
    (value: number) => Math.max(min, Math.min(max, value)),
    [min, max],
  )

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.currentTarget.setPointerCapture(event.pointerId)
      start.current = {
        pointer: orientation === 'horizontal' ? event.clientY : event.clientX,
        size,
      }
    },
    [orientation, size],
  )

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
      const current = orientation === 'horizontal' ? event.clientY : event.clientX
      // The resized pane sits after the divider, so dragging back toward the
      // start of the axis makes it larger.
      onChange(clamp(start.current.size - (current - start.current.pointer)))
    },
    [orientation, onChange, clamp],
  )

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const grow = orientation === 'horizontal' ? 'ArrowUp' : 'ArrowLeft'
      const shrink = orientation === 'horizontal' ? 'ArrowDown' : 'ArrowRight'

      if (event.key === grow) onChange(clamp(size + step))
      else if (event.key === shrink) onChange(clamp(size - step))
      else if (event.key === 'Home') onChange(min)
      else if (event.key === 'End') onChange(max)
      else return

      event.preventDefault()
    },
    [orientation, onChange, clamp, size, step, min, max],
  )

  const horizontal = orientation === 'horizontal'

  return (
    <div
      role="separator"
      aria-orientation={horizontal ? 'horizontal' : 'vertical'}
      aria-label={label}
      aria-valuenow={Math.round(size)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onKeyDown={handleKeyDown}
      onDoubleClick={() => onChange(clamp((min + max) / 2))}
      className={[
        'group relative shrink-0 bg-ink-line/60 hover:bg-lo/50 transition-colors',
        horizontal ? 'h-px w-full cursor-row-resize' : 'w-px h-full cursor-col-resize',
      ].join(' ')}
    >
      {/* A 1px line is the right look but a terrible hit target, so the grab
          area is widened invisibly around it. */}
      <span
        className={[
          'absolute',
          horizontal ? '-top-2 -bottom-2 left-0 right-0' : '-left-2 -right-2 top-0 bottom-0',
        ].join(' ')}
      />
      {/* Grip, visible on hover so the divider advertises that it moves. */}
      <span
        className={[
          'absolute bg-lo/70 rounded-full opacity-0 group-hover:opacity-100 group-focus:opacity-100 transition-opacity',
          horizontal
            ? 'left-1/2 -translate-x-1/2 -top-[1.5px] h-[4px] w-9'
            : 'top-1/2 -translate-y-1/2 -left-[1.5px] w-[4px] h-9',
        ].join(' ')}
        aria-hidden
      />
    </div>
  )
}
