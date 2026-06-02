import { useCallback, useState } from 'react'

export interface UseChartZoomOptions {
  initialDomain?: [number, number]
  /** When true, clamp zoom to [0, 1] (probability metrics). Default: unbounded. */
  clampZeroOne?: boolean
}

/** True when the user is performing a macOS-style zoom gesture (⌘+scroll or trackpad pinch). */
export function isZoomWheelEvent(e: WheelEvent): boolean {
  return e.metaKey || e.ctrlKey
}

/** Convert wheel delta to a multiplicative domain factor (>1 zooms out, <1 zooms in). */
export function wheelDeltaToZoomFactor(deltaY: number): number {
  return Math.exp(deltaY * 0.01)
}

/** Pinch scale ratio from Safari gesturechange (>1 = fingers spreading). */
export function pinchScaleToZoomFactor(scaleRatio: number): number {
  return scaleRatio > 0 ? 1 / scaleRatio : 1
}

export function useChartZoom(options: UseChartZoomOptions = {}) {
  const { initialDomain = [0, 1], clampZeroOne = false } = options
  const [domain, setDomain] = useState<[number, number]>(initialDomain)

  const isZoomed = domain[0] !== initialDomain[0] || domain[1] !== initialDomain[1]

  const clamp = useCallback(
    (lo: number, hi: number): [number, number] => {
      if (!clampZeroOne) return [lo, hi]
      return [Math.max(0, lo), Math.min(1, hi)]
    },
    [clampZeroOne],
  )

  const zoomByFactor = useCallback(
    (factor: number) => {
      if (factor <= 0 || !Number.isFinite(factor)) return
      setDomain(([lo, hi]) => {
        const center = (lo + hi) / 2
        const half = ((hi - lo) * factor) / 2
        return clamp(center - half, center + half)
      })
    },
    [clamp],
  )

  const fitToData = useCallback(
    (dataMin: number, dataMax: number, minSpan = 0.02) => {
      const span = Math.max(dataMax - dataMin, minSpan)
      const pad = Math.max(span * 0.12, minSpan * 0.5)
      setDomain(clamp(dataMin - pad, dataMax + pad))
    },
    [clamp],
  )

  const reset = useCallback(() => setDomain(initialDomain), [initialDomain])

  const handleWheel = useCallback(
    (e: WheelEvent) => {
      if (!isZoomWheelEvent(e)) return
      e.preventDefault()
      e.stopPropagation()
      zoomByFactor(wheelDeltaToZoomFactor(e.deltaY))
    },
    [zoomByFactor],
  )

  const handlePinchScale = useCallback(
    (scaleRatio: number) => {
      zoomByFactor(pinchScaleToZoomFactor(scaleRatio))
    },
    [zoomByFactor],
  )

  return {
    domain,
    setDomain,
    zoomByFactor,
    fitToData,
    reset,
    handleWheel,
    handlePinchScale,
    isZoomed,
    initialDomain,
  }
}

/** Numeric X-axis zoom for scatter charts. */
export function useNumericZoom(initial: [number, number] | 'auto' = 'auto') {
  const [xDomain, setXDomain] = useState<[number | 'auto', number | 'auto']>(
    initial === 'auto' ? ['auto', 'auto'] : initial,
  )

  const isXZoomed = xDomain[0] !== 'auto' || xDomain[1] !== 'auto'

  const materializeDomain = useCallback(
    (dataMin: number, dataMax: number): [number, number] => {
      if (xDomain[0] !== 'auto' && xDomain[1] !== 'auto') {
        return [xDomain[0] as number, xDomain[1] as number]
      }
      const center = (dataMin + dataMax) / 2
      const half = (dataMax - dataMin) / 2
      return [Math.max(0, center - half), center + half]
    },
    [xDomain],
  )

  const zoomXByFactor = useCallback(
    (factor: number, dataMin: number, dataMax: number) => {
      if (factor <= 0 || !Number.isFinite(factor)) return
      setXDomain(([lo, hi]) => {
        const [curLo, curHi] =
          lo === 'auto' || hi === 'auto'
            ? materializeDomain(dataMin, dataMax)
            : [lo as number, hi as number]
        const center = (curLo + curHi) / 2
        const half = ((curHi - curLo) * factor) / 2
        return [Math.max(0, center - half), center + half]
      })
    },
    [materializeDomain],
  )

  const fitXToData = useCallback((dataMin: number, dataMax: number) => {
    const span = Math.max(dataMax - dataMin, 1)
    const pad = span * 0.12
    setXDomain([Math.max(0, dataMin - pad), dataMax + pad])
  }, [])

  const resetX = useCallback(() => setXDomain(['auto', 'auto']), [])

  return { xDomain, setXDomain, zoomXByFactor, fitXToData, resetX, isXZoomed, materializeDomain }
}
