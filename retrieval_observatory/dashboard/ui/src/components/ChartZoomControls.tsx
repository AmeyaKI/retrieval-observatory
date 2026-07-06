interface Props {
  domain: [number, number]
  isZoomed: boolean
  onFit?: () => void
  onReset: () => void
  onZoomIn?: () => void
  onZoomOut?: () => void
  onExpand?: () => void
  compact?: boolean
  fitLabel?: string
}

export default function ChartZoomControls({
  domain,
  isZoomed,
  onFit,
  onReset,
  onZoomIn,
  onZoomOut,
  onExpand,
  compact = true,
  fitLabel = 'Fit',
}: Props) {
  const zoomHint = 'Pinch to zoom · Drag to pan'

  if (compact) {
    return (
      <div className="flex justify-end items-center gap-1.5 mb-1 flex-wrap">
        {isZoomed && (
          <span className="text-[10px] text-gray-400 dark:text-slate-500 font-mono">
            {domain[0].toFixed(2)}–{domain[1].toFixed(2)}
          </span>
        )}
        {onZoomIn && (
          <button
            type="button"
            onClick={onZoomIn}
            title="Zoom in"
            className="text-xs text-gray-500 dark:text-slate-400 hover:text-indigo-600 border border-gray-200 dark:border-slate-700 hover:border-indigo-300 rounded px-1.5 py-0.5 font-mono leading-none"
          >
            +
          </button>
        )}
        {onZoomOut && (
          <button
            type="button"
            onClick={onZoomOut}
            title="Zoom out"
            className="text-xs text-gray-500 dark:text-slate-400 hover:text-indigo-600 border border-gray-200 dark:border-slate-700 hover:border-indigo-300 rounded px-1.5 py-0.5 font-mono leading-none"
          >
            −
          </button>
        )}
        {onFit && (
          <button
            type="button"
            onClick={onFit}
            title="Fit axis to data range"
            className="text-xs text-gray-500 dark:text-slate-400 hover:text-indigo-600 border border-gray-200 dark:border-slate-700 hover:border-indigo-300 rounded px-1.5 py-0.5"
          >
            {fitLabel}
          </button>
        )}
        {isZoomed && (
          <button
            type="button"
            onClick={onReset}
            className="text-xs text-indigo-600 hover:text-indigo-800 border border-indigo-200 rounded px-2 py-0.5 font-medium"
          >
            Reset
          </button>
        )}
        {onExpand && (
          <button
            type="button"
            onClick={onExpand}
            title="Open in expanded view"
            className="text-xs text-gray-400 dark:text-slate-500 hover:text-gray-600 border border-gray-200 dark:border-slate-700 rounded px-2 py-0.5"
          >
            Expand ⤢
          </button>
        )}
        <span className="text-[10px] text-gray-400 dark:text-slate-500 w-full text-right sm:w-auto">{zoomHint}</span>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-gray-500 dark:text-slate-400 font-medium">Y-axis:</span>
        {onZoomIn && (
          <button
            type="button"
            onClick={onZoomIn}
            title="Zoom in"
            className="text-xs bg-white dark:bg-slate-900 text-gray-600 dark:text-slate-300 hover:bg-gray-50 border border-gray-200 dark:border-slate-700 rounded px-2 py-1 font-mono"
          >
            +
          </button>
        )}
        {onZoomOut && (
          <button
            type="button"
            onClick={onZoomOut}
            title="Zoom out"
            className="text-xs bg-white dark:bg-slate-900 text-gray-600 dark:text-slate-300 hover:bg-gray-50 border border-gray-200 dark:border-slate-700 rounded px-2 py-1 font-mono"
          >
            −
          </button>
        )}
        {onFit && (
          <button
            type="button"
            onClick={onFit}
            className="text-xs bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200 rounded px-2 py-1 font-medium"
          >
            Fit to data
          </button>
        )}
        <span className="text-xs text-gray-500 dark:text-slate-400 font-mono px-2 min-w-[110px] text-center select-none">
          {domain[0].toFixed(2)} – {domain[1].toFixed(2)}
        </span>
        {isZoomed && (
          <button
            type="button"
            onClick={onReset}
            className="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 border border-gray-200 dark:border-slate-700 rounded px-2 py-1"
          >
            Reset
          </button>
        )}
      </div>
      <p className="text-xs text-gray-400 dark:text-slate-500">{zoomHint} · Click legend to hide/show series</p>
    </div>
  )
}
