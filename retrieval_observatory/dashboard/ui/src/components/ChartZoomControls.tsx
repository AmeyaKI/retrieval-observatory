interface Props {
  domain: [number, number]
  isZoomed: boolean
  onFit?: () => void
  onReset: () => void
  onExpand?: () => void
  compact?: boolean
  fitLabel?: string
}

export default function ChartZoomControls({
  domain,
  isZoomed,
  onFit,
  onReset,
  onExpand,
  compact = true,
  fitLabel = 'Fit',
}: Props) {
  const zoomHint = '⌘ + trackpad pinch or scroll to zoom'

  if (compact) {
    return (
      <div className="flex justify-end items-center gap-1.5 mb-1 flex-wrap">
        {isZoomed && (
          <span className="text-[10px] text-gray-400 font-mono">
            {domain[0].toFixed(2)}–{domain[1].toFixed(2)}
          </span>
        )}
        {onFit && (
          <button
            type="button"
            onClick={onFit}
            title="Fit axis to data range"
            className="text-xs text-gray-500 hover:text-indigo-600 border border-gray-200 hover:border-indigo-300 rounded px-1.5 py-0.5"
          >
            {fitLabel}
          </button>
        )}
        {isZoomed && (
          <button
            type="button"
            onClick={onReset}
            className="text-xs text-indigo-600 hover:text-indigo-800 border border-indigo-200 rounded px-2 py-0.5"
          >
            Reset
          </button>
        )}
        {onExpand && (
          <button
            type="button"
            onClick={onExpand}
            className="text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded px-2 py-0.5"
          >
            Expand ⤢
          </button>
        )}
        <span className="text-[10px] text-gray-400 w-full text-right sm:w-auto">{zoomHint}</span>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-gray-500 font-medium">Y-axis:</span>
        {onFit && (
          <button
            type="button"
            onClick={onFit}
            className="text-xs bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200 rounded px-2 py-1 font-medium"
          >
            Fit to data
          </button>
        )}
        <span className="text-xs text-gray-500 font-mono px-2 min-w-[110px] text-center select-none">
          {domain[0].toFixed(2)} – {domain[1].toFixed(2)}
        </span>
        {isZoomed && (
          <button
            type="button"
            onClick={onReset}
            className="text-xs text-gray-500 hover:text-gray-700 border border-gray-200 rounded px-2 py-1"
          >
            Reset
          </button>
        )}
      </div>
      <p className="text-xs text-gray-400">{zoomHint} · Click legend to hide/show series</p>
    </div>
  )
}
