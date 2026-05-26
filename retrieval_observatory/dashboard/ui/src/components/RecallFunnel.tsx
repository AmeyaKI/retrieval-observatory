import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from 'recharts'
import { MetricsMap } from '../api'
import { formatSeriesKey } from '../utils/formatMetricKey'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'

interface Props {
  metrics: MetricsMap
}

const COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444']

export default function RecallFunnel({ metrics }: Props) {
  // For each pipeline+stage, collect highest-K recall
  type StageEntry = { mean: number; k: number }
  // stageRecall[stageLabel][seriesLabel] = { mean, k }
  const stageRecall: Record<string, Record<string, StageEntry>> = {}
  const seriesSet = new Set<string>()

  // Track which pipeline IDs have >1 stage index
  const pipelineMaxStage: Record<string, number> = {}
  for (const [, entry] of Object.entries(metrics)) {
    if (entry.metric_name !== 'recall') continue
    pipelineMaxStage[entry.pipeline_id] = Math.max(
      pipelineMaxStage[entry.pipeline_id] ?? 0,
      entry.stage_index
    )
  }

  for (const [, entry] of Object.entries(metrics)) {
    if (entry.metric_name !== 'recall') continue
    const isMultiStage = (pipelineMaxStage[entry.pipeline_id] ?? 0) > 0
    const seriesLabel = formatSeriesKey(entry.pipeline_id, entry.stage_index, isMultiStage)
    const stageLabel = entry.stage_index === 0 ? 'Stage 0 · Retrieval' : `Stage ${entry.stage_index} · Reranking`
    seriesSet.add(seriesLabel)
    if (!stageRecall[stageLabel]) stageRecall[stageLabel] = {}
    const existing = stageRecall[stageLabel][seriesLabel]
    if (existing === undefined || entry.k > existing.k) {
      stageRecall[stageLabel][seriesLabel] = { mean: entry.mean, k: entry.k }
    }
  }

  const stages = Object.keys(stageRecall).sort()
  const seriesList = [...seriesSet]

  if (stages.length === 0) return <p className="text-sm text-gray-400">No stage data.</p>

  const chartData = stages.map((stage) => {
    const row: Record<string, string | number> = { stage }
    for (const s of seriesList) {
      row[s] = stageRecall[stage][s]?.mean ?? 0
    }
    return row
  })

  // Custom tooltip to show K value
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null
    return (
      <div className="bg-white border border-gray-200 rounded shadow p-2 text-xs">
        <p className="font-semibold mb-1">{label}</p>
        {payload.map((p: any) => {
          const stageEntry = stageRecall[label]?.[p.dataKey]
          return (
            <p key={p.dataKey} style={{ color: p.color }}>
              {p.dataKey}: {p.value.toFixed(4)}
              {stageEntry ? ` (Recall@${stageEntry.k})` : ''}
            </p>
          )
        })}
      </div>
    )
  }

  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">
        Each bar shows max-K recall at that stage. Stage 0 = initial retrieval; Stage 1+ = reranking output.
        <MetricTooltip text={METRIC_GLOSSARY.stage} />
      </p>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey="stage" tick={{ fontSize: 11 }} />
          <YAxis tickFormatter={(v) => v.toFixed(2)} tick={{ fontSize: 12 }} domain={[0, 1]} />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {seriesList.map((s, i) => (
            <Bar key={s} dataKey={s} fill={COLORS[i % COLORS.length]} radius={[3, 3, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
