import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from 'recharts'
import { MetricsMap } from '../api'

interface Props {
  metrics: MetricsMap
}

const COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444']

export default function RecallFunnel({ metrics }: Props) {
  // For each pipeline, collect recall@10 (or highest K) per stage
  const pipelines = new Set<string>()
  const stageRecall: Record<string, Record<string, number>> = {}  // stage → pipeline → mean

  for (const [, entry] of Object.entries(metrics)) {
    if (entry.metric_name !== 'recall') continue
    pipelines.add(entry.pipeline_id)
    const stageKey = `Stage ${entry.stage_index}`
    if (!stageRecall[stageKey]) stageRecall[stageKey] = {}
    // Keep highest-K recall per pipeline per stage
    const existing = stageRecall[stageKey][entry.pipeline_id]
    if (existing === undefined || entry.k > (stageRecall[stageKey][`${entry.pipeline_id}_k`] ?? 0)) {
      stageRecall[stageKey][entry.pipeline_id] = entry.mean
      stageRecall[stageKey][`${entry.pipeline_id}_k`] = entry.k
    }
  }

  const stages = Object.keys(stageRecall).sort()
  const pipelineList = [...pipelines]

  if (stages.length === 0) return <p className="text-sm text-gray-400">No stage data.</p>

  const chartData = stages.map((stage) => ({
    stage,
    ...Object.fromEntries(pipelineList.map((p) => [p, stageRecall[stage][p] ?? 0])),
  }))

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={chartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="stage" tick={{ fontSize: 12 }} />
        <YAxis tickFormatter={(v) => v.toFixed(2)} tick={{ fontSize: 12 }} domain={[0, 1]} />
        <Tooltip formatter={(v: number) => v.toFixed(4)} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {pipelineList.map((p, i) => (
          <Bar key={p} dataKey={p} fill={COLORS[i % COLORS.length]} radius={[3, 3, 0, 0]} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}
