import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from 'recharts'
import { MetricsMap } from '../api'

interface Props {
  metrics: MetricsMap
}

export default function LatencyChart({ metrics }: Props) {
  // Collect latency_p50/p95/p99 per (pipeline, stage)
  const groups: Record<string, Record<string, number>> = {}

  for (const [, entry] of Object.entries(metrics)) {
    if (!entry.metric_name.startsWith('latency_p')) continue
    const key = `${entry.pipeline_id} / stage${entry.stage_index}`
    if (!groups[key]) groups[key] = {}
    groups[key][entry.metric_name] = entry.mean
  }

  const groupKeys = Object.keys(groups).sort()
  if (groupKeys.length === 0) return <p className="text-sm text-gray-400">No latency data.</p>

  const chartData = groupKeys.map((k) => ({
    label: k,
    p50: groups[k]['latency_p50'] ?? 0,
    p95: groups[k]['latency_p95'] ?? 0,
    p99: groups[k]['latency_p99'] ?? 0,
  }))

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={chartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="label" tick={{ fontSize: 11 }} />
        <YAxis tickFormatter={(v) => `${v.toFixed(0)}ms`} tick={{ fontSize: 11 }} />
        <Tooltip formatter={(v: number) => `${v.toFixed(2)} ms`} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="p50" fill="#6366f1" name="P50" radius={[3, 3, 0, 0]} />
        <Bar dataKey="p95" fill="#f59e0b" name="P95" radius={[3, 3, 0, 0]} />
        <Bar dataKey="p99" fill="#ef4444" name="P99" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}
