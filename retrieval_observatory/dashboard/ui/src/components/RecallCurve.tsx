import { useCallback, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, ErrorBar, ReferenceLine,
} from 'recharts'
import { MetricsMap } from '../api'
import { formatSeriesKey } from '../utils/formatMetricKey'
import { fmtQuality } from '../utils/format'
import { ChartModal } from './ChartModal'

interface Props {
  metrics: MetricsMap
  baselines?: Record<string, number>
}

const COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6']

export default function RecallCurve({ metrics, baselines = {} }: Props) {
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState(false)
  const [yDomain, setYDomain] = useState<[number, number]>([0, 1])
  const isYZoomed = yDomain[0] !== 0 || yDomain[1] !== 1

  const toggleSeries = (dataKey: string) => {
    setHiddenSeries((prev) => {
      const next = new Set(prev)
      next.has(dataKey) ? next.delete(dataKey) : next.add(dataKey)
      return next
    })
  }

  const seriesMap: Record<string, Record<number, { mean: number; ci_low: number; ci_high: number }>> = {}
  const pipelineMaxStage: Record<string, number> = {}

  for (const [, entry] of Object.entries(metrics)) {
    if (entry.metric_name !== 'recall' || entry.k === 0 || entry.stage_index < 0) continue
    pipelineMaxStage[entry.pipeline_id] = Math.max(
      pipelineMaxStage[entry.pipeline_id] ?? 0,
      entry.stage_index
    )
  }

  for (const [, entry] of Object.entries(metrics)) {
    if (entry.metric_name !== 'recall' || entry.k === 0 || entry.stage_index < 0) continue
    const isMultiStage = (pipelineMaxStage[entry.pipeline_id] ?? 0) > 0
    const seriesKey = formatSeriesKey(entry.pipeline_id, entry.stage_index, isMultiStage)
    if (!seriesMap[seriesKey]) seriesMap[seriesKey] = {}
    seriesMap[seriesKey][entry.k] = { mean: entry.mean, ci_low: entry.ci_low, ci_high: entry.ci_high }
  }

  const seriesKeys = Object.keys(seriesMap)
  if (seriesKeys.length === 0) {
    return <p className="text-sm text-gray-400">No recall metrics found.</p>
  }

  const allK = [...new Set(seriesKeys.flatMap((s) => Object.keys(seriesMap[s]).map(Number)))].sort((a, b) => a - b)

  const chartData = allK.map((k) => {
    const row: Record<string, number> = { k }
    for (const sk of seriesKeys) {
      const v = seriesMap[sk][k]
      if (v) {
        row[sk] = v.mean
        row[`${sk}_err`] = (v.ci_high - v.ci_low) / 2
      }
    }
    return row
  })

  // Compute actual data bounds across visible series for smart zoom
  const visibleValues = seriesKeys
    .filter((sk) => !hiddenSeries.has(sk))
    .flatMap((sk) => chartData.map((row) => row[sk]).filter((v) => v != null) as number[])
  const dataMin = visibleValues.length > 0 ? Math.min(...visibleValues) : 0
  const dataMax = visibleValues.length > 0 ? Math.max(...visibleValues) : 1

  const fitToData = () => {
    const pad = Math.max((dataMax - dataMin) * 0.12, 0.02)
    setYDomain([Math.max(0, dataMin - pad), Math.min(1, dataMax + pad)])
  }

  const zoomIn = () => setYDomain(([lo, hi]) => {
    const center = (lo + hi) / 2
    const half = (hi - lo) * 0.85 / 2
    return [Math.max(0, center - half), Math.min(1, center + half)]
  })

  const zoomOut = () => setYDomain(([lo, hi]) => {
    const center = (lo + hi) / 2
    const half = Math.min((hi - lo) * 1.2 / 2, 0.5)
    return [Math.max(0, center - half), Math.min(1, center + half)]
  })

  const handleWheel = useCallback((e: React.WheelEvent<HTMLDivElement>) => {
    if (!e.ctrlKey) return
    e.preventDefault()
    const factor = e.deltaY > 0 ? 1.15 : 0.87
    setYDomain(([lo, hi]) => {
      const center = (lo + hi) / 2
      const half = Math.min(((hi - lo) * factor) / 2, 0.5)
      return [Math.max(0, center - half), Math.min(1, center + half)]
    })
  }, [])

  const referenceLines: Array<{ k: number; value: number }> = allK
    .map((k) => ({ k, value: baselines[`recall@${k}`] }))
    .filter((r) => r.value !== undefined)

  const renderChart = (height: number) => (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={chartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="k" label={{ value: 'K', position: 'insideBottomRight', offset: -4 }} tick={{ fontSize: 12 }} />
        <YAxis tickFormatter={(v) => v.toFixed(2)} tick={{ fontSize: 12 }} domain={[yDomain[0], yDomain[1]]} />
        <Tooltip formatter={(v: number) => fmtQuality(v)} />
        <Legend
          wrapperStyle={{ fontSize: 12 }}
          onClick={(data: any) => toggleSeries(data.dataKey as string)}
          formatter={(value: any, entry: any) => (
            <span style={{
              opacity: hiddenSeries.has(entry.dataKey) ? 0.35 : 1,
              cursor: 'pointer',
              textDecoration: hiddenSeries.has(entry.dataKey) ? 'line-through' : 'none',
            }}>
              {value}
            </span>
          )}
        />
        {seriesKeys.map((sk, i) => (
          <Line
            key={sk}
            type="monotone"
            dataKey={sk}
            hide={hiddenSeries.has(sk)}
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={2}
            dot={{ r: 4 }}
            activeDot={{ r: 6 }}
          >
            <ErrorBar dataKey={`${sk}_err`} width={4} strokeWidth={1.5} stroke={COLORS[i % COLORS.length]} direction="y" />
          </Line>
        ))}
        {referenceLines.map(({ k, value }) => (
          <ReferenceLine
            key={`ref-recall-${k}`}
            y={value}
            stroke="#9ca3af"
            strokeDasharray="6 3"
            label={{ value: `BM25 Ref @${k}: ${value.toFixed(3)}`, position: 'right', fontSize: 10, fill: '#9ca3af' }}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )

  const footer = referenceLines.length > 0 && (
    <p className="text-xs text-gray-400 mt-1">Dashed line: published BM25 (Elasticsearch) baseline from BEIR benchmark.</p>
  )

  // Compact controls for the inline chart
  const inlineControls = (
    <div className="flex justify-end items-center gap-1.5 mb-1">
      {isYZoomed && (
        <span className="text-[10px] text-gray-400 font-mono">
          Y: {yDomain[0].toFixed(2)}–{yDomain[1].toFixed(2)}
        </span>
      )}
      <button onClick={fitToData} title="Fit Y-axis to data range" className="text-xs text-gray-500 hover:text-indigo-600 border border-gray-200 hover:border-indigo-300 rounded px-1.5 py-0.5">
        Fit
      </button>
      <button onClick={zoomIn} title="Zoom in" className="text-xs font-bold text-gray-500 hover:text-indigo-600 border border-gray-200 hover:border-indigo-300 rounded px-2 py-0.5">
        +
      </button>
      <button onClick={zoomOut} title="Zoom out" className="text-xs font-bold text-gray-500 hover:text-indigo-600 border border-gray-200 hover:border-indigo-300 rounded px-2 py-0.5">
        −
      </button>
      {isYZoomed && (
        <button onClick={() => setYDomain([0, 1])} className="text-xs text-indigo-600 hover:text-indigo-800 border border-indigo-200 rounded px-2 py-0.5">
          Reset
        </button>
      )}
      <button
        onClick={() => setExpanded(true)}
        className="text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded px-2 py-0.5"
      >
        Expand ⤢
      </button>
    </div>
  )

  // Prominent controls for the expanded modal
  const expandedControls = (
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500 font-medium">Y-axis:</span>
        <button
          onClick={fitToData}
          className="text-xs bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200 rounded px-2 py-1 font-medium"
          title="Fit Y-axis to the actual data range so lines spread apart"
        >
          Fit to data
        </button>
        <div className="flex items-center border border-gray-200 rounded overflow-hidden">
          <button
            onClick={zoomOut}
            className="text-sm font-bold text-gray-600 hover:bg-gray-100 px-3 py-1 border-r border-gray-200"
            title="Zoom out — widen Y range"
          >
            −
          </button>
          <span className="text-xs text-gray-500 font-mono px-3 min-w-[110px] text-center select-none">
            {yDomain[0].toFixed(2)} – {yDomain[1].toFixed(2)}
          </span>
          <button
            onClick={zoomIn}
            className="text-sm font-bold text-gray-600 hover:bg-gray-100 px-3 py-1 border-l border-gray-200"
            title="Zoom in — narrow Y range to see differences"
          >
            +
          </button>
        </div>
        {isYZoomed && (
          <button
            onClick={() => setYDomain([0, 1])}
            className="text-xs text-gray-500 hover:text-gray-700 border border-gray-200 rounded px-2 py-1"
          >
            Reset
          </button>
        )}
      </div>
      <p className="text-xs text-gray-400">Pinch to zoom · Click legend to hide/show series</p>
    </div>
  )

  return (
    <div>
      {inlineControls}
      <div onWheel={handleWheel} style={{ touchAction: 'none' }}>
        {renderChart(260)}
      </div>
      {footer}
      {expanded && (
        <ChartModal title="Recall@K Curves" onClose={() => setExpanded(false)}>
          {expandedControls}
          <div onWheel={handleWheel} style={{ touchAction: 'none' }}>
            {renderChart(480)}
          </div>
          {footer}
        </ChartModal>
      )}
    </div>
  )
}
