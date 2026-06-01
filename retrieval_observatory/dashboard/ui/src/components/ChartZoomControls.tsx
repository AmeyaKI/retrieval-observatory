interface Props {
  domain: [number, number]
  isZoomed: boolean
  onZoomIn: () => void
  onZoomOut: () => void
  onFit?: () => void
  onReset: () => void
  onExpand?: () => void
  compact?: boolean
  fitLabel?: string
}

export default function ChartZoomControls({
  domain,
  isZoomed,
  onZoomIn,
  onZoomOut,
  onFit,
  onReset,
  onExpand,
  compact = true,
  fitLabel = 'Fit',
}: Props) {
  if (compact) {
    return (
      <div className="flex justify-end items-center gap-1.5 mb-1">
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
        <button
          type="button"
          onClick={onZoomIn}
          title="Zoom in"
          className="text-xs font-bold text-gray-500 hover:text-indigo-600 border border-gray-200 hover:border-indigo-300 rounded px-2 py-0.5"
        >
          +
        </button>
        <button
          type="button"
          onClick={onZoomOut}
          title="Zoom out"
          className="text-xs font-bold text-gray-500 hover:text-indigo-600 border border-gray-200 hover:border-indigo-300 rounded px-2 py-0.5"
        >
          −
        </button>
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
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-2">
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
        <div className="flex items-center border border-gray-200 rounded overflow-hidden">
          <button
            type="button"
            onClick={onZoomOut}
            className="text-sm font-bold text-gray-600 hover:bg-gray-100 px-3 py-1 border-r border-gray-200"
          >
            −
          </button>
          <span className="text-xs text-gray-500 font-mono px-3 min-w-[110px] text-center select-none">
            {domain[0].toFixed(2)} – {domain[1].toFixed(2)}
          </span>
          <button
            type="button"
            onClick={onZoomIn}
            className="text-sm font-bold text-gray-600 hover:bg-gray-100 px-3 py-1 border-l border-gray-200"
          >
            +
          </button>
        </div>
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
      <p className="text-xs text-gray-400">⌘/Ctrl + scroll on chart to zoom · Click legend to hide/show series</p>
    </div>
  )
}
