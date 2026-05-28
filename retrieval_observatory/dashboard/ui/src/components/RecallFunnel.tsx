import { useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from 'recharts'
import { MetricsMap } from '../api'
import { formatSeriesKey } from '../utils/formatMetricKey'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'
import { fmtQuality } from '../utils/format'

interface Props {
  metrics: MetricsMap
}

const RECALL_COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444']
const NDCG_COLORS = ['#818cf8', '#fcd34d', '#6ee7b7', '#fca5a5']

export default function RecallFunnel({ metrics }: Props) {
  const [hiddenRecall, setHiddenRecall] = useState<Set<string>>(new Set())
  const [hiddenNdcg, setHiddenNdcg] = useState<Set<string>>(new Set())

  const toggleRecall = (dataKey: string) => setHiddenRecall((prev) => {
    const next = new Set(prev); next.has(dataKey) ? next.delete(dataKey) : next.add(dataKey); return next
  })
  const toggleNdcg = (dataKey: string) => setHiddenNdcg((prev) => {
    const next = new Set(prev); next.has(dataKey) ? next.delete(dataKey) : next.add(dataKey); return next
  })

  type StageEntry = { mean: number; k: number }
  const stageRecall: Record<string, Record<string, StageEntry>> = {}
  const stageNdcg: Record<string, Record<string, number>> = {}
  const seriesSet = new Set<string>()

  const pipelineMaxStage: Record<string, number> = {}
  for (const [, entry] of Object.entries(metrics)) {
    if (entry.metric_name !== 'recall' && entry.metric_name !== 'ndcg') continue
    if (entry.stage_index < 0) continue
    pipelineMaxStage[entry.pipeline_id] = Math.max(
      pipelineMaxStage[entry.pipeline_id] ?? 0,
      entry.stage_index
    )
  }

  for (const [, entry] of Object.entries(metrics)) {
    if (entry.stage_index < 0) continue
    const isMultiStage = (pipelineMaxStage[entry.pipeline_id] ?? 0) > 0
    const seriesLabel = formatSeriesKey(entry.pipeline_id, entry.stage_index, isMultiStage)
    const stageLabel = entry.stage_index === 0 ? 'Stage 0 · Retrieval' : `Stage ${entry.stage_index} · Reranking`

    if (entry.metric_name === 'recall') {
      seriesSet.add(seriesLabel)
      if (!stageRecall[stageLabel]) stageRecall[stageLabel] = {}
      const existing = stageRecall[stageLabel][seriesLabel]
      if (existing === undefined || entry.k > existing.k) {
        stageRecall[stageLabel][seriesLabel] = { mean: entry.mean, k: entry.k }
      }
    }
    if (entry.metric_name === 'ndcg' && entry.k === 10) {
      seriesSet.add(seriesLabel)
      if (!stageNdcg[stageLabel]) stageNdcg[stageLabel] = {}
      stageNdcg[stageLabel][seriesLabel] = entry.mean
    }
  }

  const stages = Object.keys(stageRecall).sort()
  const seriesList = [...seriesSet]

  if (stages.length === 0) return <p className="text-sm text-gray-400">No stage data.</p>

  const hasMultipleStages = stages.length > 1

  const chartData = stages.map((stage) => {
    const row: Record<string, string | number> = { stage }
    for (const s of seriesList) {
      row[`recall__${s}`] = stageRecall[stage]?.[s]?.mean ?? 0
      row[`ndcg__${s}`] = stageNdcg[stage]?.[s] ?? 0
    }
    return row
  })

  const makeLegendFormatter = (hiddenSet: Set<string>) =>
    (value: string, entry: any) => (
      <span style={{
        opacity: hiddenSet.has(entry.dataKey) ? 0.35 : 1,
        cursor: 'pointer',
        textDecoration: hiddenSet.has(entry.dataKey) ? 'line-through' : 'none',
      }}>
        {value}
      </span>
    )

  const RecallTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null
    return (
      <div className="bg-white border border-gray-200 rounded shadow p-2 text-xs">
        <p className="font-semibold mb-1">{label}</p>
        {payload.map((p: any) => {
          const s = p.dataKey.replace(/^recall__/, '')
          const stageEntry = stageRecall[label]?.[s]
          return (
            <p key={p.dataKey} style={{ color: p.color }}>
              {`Recall@${stageEntry?.k ?? '?'} ${s}: ${fmtQuality(p.value)}`}
            </p>
          )
        })}
      </div>
    )
  }

  const NdcgTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null
    return (
      <div className="bg-white border border-gray-200 rounded shadow p-2 text-xs">
        <p className="font-semibold mb-1">{label}</p>
        {payload.map((p: any) => {
          const s = p.dataKey.replace(/^ndcg__/, '')
          return (
            <p key={p.dataKey} style={{ color: p.color }}>
              {`NDCG@10 ${s}: ${fmtQuality(p.value)}`}
            </p>
          )
        })}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <p className="text-xs text-gray-500">
        Each group shows per-stage metrics across pipeline combinations. Click legend items to show/hide series.
        <MetricTooltip text={METRIC_GLOSSARY.stage} />
      </p>

      {/* Max-K Recall chart */}
      <div>
        <p className="text-xs font-semibold text-gray-600 mb-1">Max-K Recall per Stage</p>
        {hasMultipleStages && (
          <div className="mb-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800">
            <span className="font-semibold">Note on Recall drop Stage 0 → Stage 1:</span> Stage 0 recall is measured
            at a wide k (e.g. 100) and is the <span className="font-semibold">upper bound</span> for later stages.
            The drop at Stage 1 reflects intentional truncation (100 → 20 docs), not a regression.
            Watch <span className="font-semibold">NDCG@10</span> below — if reranking works, it should <span className="font-semibold">rise</span> even as recall falls.
          </div>
        )}
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="stage" tick={{ fontSize: 11 }} />
            <YAxis tickFormatter={(v) => v.toFixed(2)} tick={{ fontSize: 12 }} domain={[0, 1]} />
            <Tooltip content={<RecallTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: 11 }}
              onClick={(data) => toggleRecall(data.dataKey as string)}
              formatter={makeLegendFormatter(hiddenRecall)}
            />
            {seriesList.map((s, i) => (
              <Bar
                key={`recall__${s}`}
                dataKey={`recall__${s}`}
                name={`Recall  ${s}`}
                hide={hiddenRecall.has(`recall__${s}`)}
                fill={RECALL_COLORS[i % RECALL_COLORS.length]}
                radius={[3, 3, 0, 0]}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* NDCG@10 chart */}
      <div>
        <p className="text-xs font-semibold text-gray-600 mb-1">NDCG@10 per Stage</p>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="stage" tick={{ fontSize: 11 }} />
            <YAxis tickFormatter={(v) => v.toFixed(2)} tick={{ fontSize: 12 }} domain={[0, 1]} />
            <Tooltip content={<NdcgTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: 11 }}
              onClick={(data) => toggleNdcg(data.dataKey as string)}
              formatter={makeLegendFormatter(hiddenNdcg)}
            />
            {seriesList.map((s, i) => (
              <Bar
                key={`ndcg__${s}`}
                dataKey={`ndcg__${s}`}
                name={`NDCG@10  ${s}`}
                hide={hiddenNdcg.has(`ndcg__${s}`)}
                fill={NDCG_COLORS[i % NDCG_COLORS.length]}
                radius={[3, 3, 0, 0]}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
