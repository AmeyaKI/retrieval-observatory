import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from 'recharts'
import { MetricsMap } from '../api'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'
import { formatSeriesKey } from '../utils/formatMetricKey'

interface Props {
  metrics: MetricsMap
}

export default function LatencyChart({ metrics }: Props) {
  // Collect latency_p50/p95/p99 per (pipeline, stage)
  const groups: Record<string, Record<string, number>> = {}
  // Track which pipelines have >1 stage for labeling
  const pipelineMaxStage: Record<string, number> = {}

  for (const [, entry] of Object.entries(metrics)) {
    if (!entry.metric_name.startsWith('latency_p')) continue
    const key = `${entry.pipeline_id}|||${entry.stage_index}`
    if (!groups[key]) groups[key] = {}
    groups[key][entry.metric_name] = entry.mean
    pipelineMaxStage[entry.pipeline_id] = Math.max(
      pipelineMaxStage[entry.pipeline_id] ?? 0,
      entry.stage_index
    )
  }

  const groupKeys = Object.keys(groups).sort()
  if (groupKeys.length === 0) return <p className="text-sm text-gray-400">No latency data.</p>

  // Build per-pipeline totals (sum across stages) when multi-stage
  const pipelineTotals: Record<string, Record<string, number>> = {}
  for (const [rawKey, vals] of Object.entries(groups)) {
    const [pipelineId] = rawKey.split('|||')
    if ((pipelineMaxStage[pipelineId] ?? 0) === 0) continue // single-stage, skip total
    if (!pipelineTotals[pipelineId]) pipelineTotals[pipelineId] = {}
    for (const [metric, v] of Object.entries(vals)) {
      pipelineTotals[pipelineId][metric] = (pipelineTotals[pipelineId][metric] ?? 0) + v
    }
  }

  const isMultiStage = (pipelineId: string) => (pipelineMaxStage[pipelineId] ?? 0) > 0

  const perStageData = groupKeys.map((rawKey) => {
    const [pipelineId, stageStr] = rawKey.split('|||')
    const stageIndex = parseInt(stageStr, 10)
    return {
      label: formatSeriesKey(pipelineId, stageIndex, isMultiStage(pipelineId)),
      p50: groups[rawKey]['latency_p50'] ?? 0,
      p95: groups[rawKey]['latency_p95'] ?? 0,
      p99: groups[rawKey]['latency_p99'] ?? 0,
    }
  })

  // Append "Total" rows for multi-stage pipelines
  const totalRows = Object.entries(pipelineTotals).map(([pipelineId, vals]) => ({
    label: `${formatSeriesKey(pipelineId, 0, false)} — Total`,
    p50: vals['latency_p50'] ?? 0,
    p95: vals['latency_p95'] ?? 0,
    p99: vals['latency_p99'] ?? 0,
    isTotal: true,
  }))

  const chartData = [...perStageData, ...totalRows]

  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">
        P50 = median · P95 = 95th percentile · P99 = tail latency
        <MetricTooltip text={`${METRIC_GLOSSARY.latency_p50}\n\n${METRIC_GLOSSARY.latency_p95}\n\n${METRIC_GLOSSARY.latency_p99}`} />
        {totalRows.length > 0 && (
          <span className="ml-2 text-gray-400">· "Total" = sum of all stages end-to-end</span>
        )}
      </p>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} />
          <YAxis tickFormatter={(v) => `${v.toFixed(0)}ms`} tick={{ fontSize: 11 }} />
          <Tooltip formatter={(v: number) => `${v.toFixed(2)} ms`} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="p50" fill="#6366f1" name="P50 (median)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="p95" fill="#f59e0b" name="P95 (tail)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="p99" fill="#ef4444" name="P99 (worst-case)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
