import { useEffect, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { fetchSegmentMetrics, SegmentMetrics } from '../api'
import { formatSeriesKey } from '../utils/formatMetricKey'
import { fmtQuality } from '../utils/format'
import { ChartModal } from './ChartModal'

interface Props {
  runId: string
  field?: string
  targetMetric?: string
}

const COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6']

export default function SegmentBreakdown({ runId, field = 'n_relevant', targetMetric = 'ndcg' }: Props) {
  const [data, setData] = useState<SegmentMetrics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState(false)

  const toggleSeries = (label: string) => {
    setHiddenSeries((prev) => {
      const next = new Set(prev)
      next.has(label) ? next.delete(label) : next.add(label)
      return next
    })
  }

  useEffect(() => {
    setData(null)
    setError(null)
    fetchSegmentMetrics(runId, field)
      .then(setData)
      .catch((e) => setError(e.message))
  }, [runId, field])

  if (error) return <p className="text-sm text-red-500">{error}</p>

  if (!data) {
    return (
      <div className="flex items-center gap-2 text-gray-400 text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 border-t-indigo-600" />
        Loading segment data...
      </div>
    )
  }

  if (Object.keys(data.segments).length === 0) {
    return <p className="text-sm text-gray-400">No segment data available for field "{field}". Re-run the pipeline to generate segment breakdowns.</p>
  }

  const segValues = Object.keys(data.segments).sort((a, b) => {
    const na = Number(a), nb = Number(b)
    return isNaN(na) || isNaN(nb) ? a.localeCompare(b) : na - nb
  })

  const seriesKeys = new Set<string>()
  const pipelineMaxStage: Record<string, number> = {}
  for (const seg of segValues) {
    for (const mKey of Object.keys(data.segments[seg])) {
      const entry = data.segments[seg][mKey]
      if (entry.metric_name === targetMetric) {
        seriesKeys.add(`${entry.pipeline_id}|${entry.stage_index}`)
        pipelineMaxStage[entry.pipeline_id] = Math.max(
          pipelineMaxStage[entry.pipeline_id] ?? 0,
          entry.stage_index
        )
      }
    }
  }

  if (seriesKeys.size === 0) {
    return <p className="text-sm text-gray-400">No "{targetMetric}" metric found in segment data.</p>
  }

  const isMultiStage = (pipelineId: string) => (pipelineMaxStage[pipelineId] ?? 0) > 0

  const chartData = segValues.map((seg) => {
    const row: Record<string, string | number> = { segment: seg }
    for (const sk of seriesKeys) {
      const [pipelineId, stageStr] = sk.split('|')
      const stageIndex = parseInt(stageStr, 10)
      const entry = Object.values(data.segments[seg]).find(
        (e) => e.pipeline_id === pipelineId && e.stage_index === stageIndex && e.metric_name === targetMetric
      )
      const label = formatSeriesKey(pipelineId, stageIndex, isMultiStage(pipelineId))
      row[label] = entry ? entry.mean : 0
    }
    return row
  })

  const seriesLabels = [...seriesKeys].map((sk) => {
    const [pipelineId, stageStr] = sk.split('|')
    return formatSeriesKey(pipelineId, parseInt(stageStr, 10), isMultiStage(pipelineId))
  })

  const metricLabel = targetMetric.toUpperCase()
  const xLabel = field === 'n_relevant' ? '# Relevant Docs' : field
  const displayLabel = (label: string) => (label.length > 36 ? `${label.slice(0, 33)}...` : label)

  const renderChart = (height: number) => (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={chartData} margin={{ top: 4, right: 20, bottom: 44, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis
          dataKey="segment"
          tick={{ fontSize: 11 }}
          label={{ value: xLabel, position: 'insideBottom', offset: -14, style: { fontSize: 11, fill: '#6b7280' } }}
        />
        <YAxis tickFormatter={(v: number) => v.toFixed(2)} tick={{ fontSize: 11 }} domain={[0, 1]} />
        <Tooltip formatter={(v: number) => fmtQuality(v)} />
        {seriesLabels.map((label, i) => (
          <Bar
            key={label}
            dataKey={label}
            hide={hiddenSeries.has(label)}
            fill={COLORS[i % COLORS.length]}
            radius={[2, 2, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )

  const legend = (
    <div className="flex flex-wrap gap-3 mt-2 justify-center">
      {seriesLabels.map((label, i) => (
        <div
          key={label}
          className="flex items-center gap-1.5 text-xs text-gray-600 max-w-[240px] cursor-pointer select-none"
          style={{ opacity: hiddenSeries.has(label) ? 0.35 : 1 }}
          onClick={() => toggleSeries(label)}
          title={hiddenSeries.has(label) ? `Click to show ${label}` : `Click to hide ${label}`}
        >
          <span
            className="inline-block w-3 h-3 rounded-sm shrink-0"
            style={{ backgroundColor: COLORS[i % COLORS.length] }}
          />
          <span className="truncate" style={{ textDecoration: hiddenSeries.has(label) ? 'line-through' : 'none' }}>
            {displayLabel(label)}
          </span>
        </div>
      ))}
    </div>
  )

  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">
        {metricLabel} by {xLabel} — each bar group is one segment value. Click legend to show/hide series.
      </p>
      <div className="flex justify-end mb-1">
        <button
          onClick={() => setExpanded(true)}
          className="text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded px-2 py-0.5"
        >
          Expand ⤢
        </button>
      </div>
      {renderChart(240)}
      {legend}
      {expanded && (
        <ChartModal title={`${metricLabel} by ${xLabel}`} onClose={() => setExpanded(false)}>
          {renderChart(480)}
          {legend}
        </ChartModal>
      )}
    </div>
  )
}
