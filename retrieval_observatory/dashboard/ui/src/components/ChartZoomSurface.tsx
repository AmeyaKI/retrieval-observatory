import { useEffect, useRef } from 'react'

interface Props {
  /** Wheel handler (must call preventDefault when handling zoom). */
  onWheel: (e: WheelEvent) => void
  /** Optional Safari trackpad pinch (gesturechange). */
  onPinchScale?: (scaleRatio: number) => void
  children: React.ReactNode
  className?: string
  /** When false, native listeners are not attached. */
  active?: boolean
}

/**
 * Captures macOS trackpad zoom gestures (⌘+pinch / ⌘+scroll, and ctrl+pinch)
 * with non-passive listeners so preventDefault blocks browser page zoom.
 */
export default function ChartZoomSurface({
  onWheel,
  onPinchScale,
  children,
  className,
  active = true,
}: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const lastGestureScale = useRef(1)

  useEffect(() => {
    const el = ref.current
    if (!el || !active) return

    const wheelHandler = (e: WheelEvent) => onWheel(e)
    el.addEventListener('wheel', wheelHandler, { passive: false })

    const onGestureStart = (e: Event) => {
      e.preventDefault()
      lastGestureScale.current = 1
    }
    const onGestureChange = (e: Event) => {
      e.preventDefault()
      const scale = (e as Event & { scale?: number }).scale ?? 1
      const ratio = scale / lastGestureScale.current
      lastGestureScale.current = scale
      if (onPinchScale && ratio > 0 && Math.abs(ratio - 1) > 1e-4) {
        onPinchScale(ratio)
      }
    }
    const onGestureEnd = (e: Event) => {
      e.preventDefault()
      lastGestureScale.current = 1
    }

    if (onPinchScale) {
      el.addEventListener('gesturestart', onGestureStart, { passive: false } as AddEventListenerOptions)
      el.addEventListener('gesturechange', onGestureChange, { passive: false } as AddEventListenerOptions)
      el.addEventListener('gestureend', onGestureEnd, { passive: false } as AddEventListenerOptions)
    }

    return () => {
      el.removeEventListener('wheel', wheelHandler)
      if (onPinchScale) {
        el.removeEventListener('gesturestart', onGestureStart)
        el.removeEventListener('gesturechange', onGestureChange)
        el.removeEventListener('gestureend', onGestureEnd)
      }
    }
  }, [onWheel, onPinchScale, active])

  return (
    <div
      ref={ref}
      className={className}
      style={{ touchAction: 'none' }}
      tabIndex={0}
    >
      {children}
    </div>
  )
}
