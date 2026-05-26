import { useEffect, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from 'recharts'
import { fetchSegmentMetrics, SegmentMetrics } from '../api'
import { formatSeriesKey } from '../utils/formatMetricKey'

interface Props {
  runId: string
  /** Metadata field to group by. Default: "n_relevant" */
  field?: string
  /** Metric to display in the chart, e.g. "ndcg@10" */
  targetMetric?: string
}

const COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6']

export default function SegmentBreakdown({ runId, field = 'n_relevant', targetMetric = 'ndcg' }: Props) {
  const [data, setData] = useState<SegmentMetrics | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setData(null)
    setError(null)
    fetchSegmentMetrics(runId, field)
      .then(setData)
      .catch((e) => setError(e.message))
  }, [runId, field])

  if (error) {
    return <p className="text-sm text-red-500">{error}</p>
  }

  if (!data || Object.keys(data.segments).length === 0) {
    return <p className="text-sm text-gray-400">No segment data available for field "{field}".</p>
  }

  // Sort segment values numerically if possible, otherwise lexicographically
  const segValues = Object.keys(data.segments).sort((a, b) => {
    const na = Number(a), nb = Number(b)
    return isNaN(na) || isNaN(nb) ? a.localeCompare(b) : na - nb
  })

  // Collect all pipeline/stage series keys that match the target metric
  const seriesKeys = new Set<string>()
  for (const seg of segValues) {
    for (const mKey of Object.keys(data.segments[seg])) {
      const entry = data.segments[seg][mKey]
      if (entry.metric_name === targetMetric) {
        seriesKeys.add(`${entry.pipeline_id}|${entry.stage_index}`)
      }
    }
  }

  if (seriesKeys.size === 0) {
    return <p className="text-sm text-gray-400">No "{targetMetric}" metric found in segment data.</p>
  }

  // Build chart data: one row per segment value
  const chartData = segValues.map((seg) => {
    const row: Record<string, string | number> = { segment: seg }
    for (const sk of seriesKeys) {
      const [pipelineId, stageStr] = sk.split('|')
      const stageIndex = parseInt(stageStr, 10)
      // Find matching metric entry for this segment
      const entry = Object.values(data.segments[seg]).find(
        (e) => e.pipeline_id === pipelineId && e.stage_index === stageIndex && e.metric_name === targetMetric
      )
      const label = formatSeriesKey(pipelineId, stageIndex)
      row[label] = entry ? entry.mean : 0
    }
    return row
  })

  const seriesLabels = [...seriesKeys].map((sk) => {
    const [pipelineId, stageStr] = sk.split('|')
    return formatSeriesKey(pipelineId, parseInt(stageStr, 10))
  })

  const metricLabel = targetMetric.toUpperCase()
  const xLabel = field === 'n_relevant' ? '# Relevant Docs' : field

  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">
        {metricLabel} by {xLabel} — each bar group is one segment value.
      </p>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={chartData} margin={{ top: 4, right: 20, bottom: 20, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            dataKey="segment"
            label={{ value: xLabel, position: 'insideBottom', offset: -12, fontSize: 11 }}
            tick={{ fontSize: 11 }}
          />
          <YAxis tickFormatter={(v: number) => v.toFixed(2)} tick={{ fontSize: 11 }} domain={[0, 1]} />
          <Tooltip formatter={(v: number) => v.toFixed(4)} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {seriesLabels.map((label, i) => (
            <Bar key={label} dataKey={label} fill={COLORS[i % COLORS.length]} radius={[2, 2, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
