import { useCallback, useState } from 'react'

export interface UseChartZoomOptions {
  initialDomain?: [number, number]
  /** When true, clamp zoom to [0, 1] (probability metrics). Default: unbounded. */
  clampZeroOne?: boolean
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

  const zoomIn = useCallback(() => {
    setDomain(([lo, hi]) => {
      const center = (lo + hi) / 2
      const half = ((hi - lo) * 0.6) / 2
      return clamp(center - half, center + half)
    })
  }, [clamp])

  const zoomOut = useCallback(() => {
    setDomain(([lo, hi]) => {
      const center = (lo + hi) / 2
      const half = ((hi - lo) * 1.4) / 2
      return clamp(center - half, center + half)
    })
  }, [clamp])

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
    (e: React.WheelEvent<HTMLDivElement>) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      const factor = e.deltaY > 0 ? 1.25 : 0.8
      setDomain(([lo, hi]) => {
        const center = (lo + hi) / 2
        const half = ((hi - lo) * factor) / 2
        return clamp(center - half, center + half)
      })
    },
    [clamp],
  )

  return { domain, setDomain, zoomIn, zoomOut, fitToData, reset, handleWheel, isZoomed, initialDomain }
}

/** Numeric X-axis zoom for scatter charts. */
export function useNumericZoom(initial: [number, number] | 'auto' = 'auto') {
  const [xDomain, setXDomain] = useState<[number | 'auto', number | 'auto']>(
    initial === 'auto' ? ['auto', 'auto'] : initial,
  )

  const isXZoomed = xDomain[0] !== 'auto' || xDomain[1] !== 'auto'

  const zoomXIn = useCallback((dataMin: number, dataMax: number) => {
    if (xDomain[0] === 'auto') {
      const center = (dataMin + dataMax) / 2
      const half = ((dataMax - dataMin) * 0.6) / 2
      setXDomain([center - half, center + half])
      return
    }
    const lo = xDomain[0] as number
    const hi = xDomain[1] as number
    const center = (lo + hi) / 2
    const half = ((hi - lo) * 0.6) / 2
    setXDomain([center - half, center + half])
  }, [xDomain])

  const zoomXOut = useCallback((dataMin: number, dataMax: number) => {
    if (xDomain[0] === 'auto') {
      const center = (dataMin + dataMax) / 2
      const half = ((dataMax - dataMin) * 1.4) / 2
      setXDomain([Math.max(0, center - half), center + half])
      return
    }
    const lo = xDomain[0] as number
    const hi = xDomain[1] as number
    const center = (lo + hi) / 2
    const half = ((hi - lo) * 1.4) / 2
    setXDomain([Math.max(0, center - half), center + half])
  }, [xDomain])

  const fitXToData = useCallback((dataMin: number, dataMax: number) => {
    const span = Math.max(dataMax - dataMin, 1)
    const pad = span * 0.12
    setXDomain([Math.max(0, dataMin - pad), dataMax + pad])
  }, [])

  const resetX = useCallback(() => setXDomain(['auto', 'auto']), [])

  return { xDomain, setXDomain, zoomXIn, zoomXOut, fitXToData, resetX, isXZoomed }
}
