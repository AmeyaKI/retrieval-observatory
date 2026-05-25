import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, ErrorBar,
} from 'recharts'
import { MetricsMap } from '../api'

interface Props {
  metrics: MetricsMap
}

const COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6']

export default function RecallCurve({ metrics }: Props) {
  // Group recall entries by pipeline_id+stage_index → {k: mean}
  const seriesMap: Record<string, Record<number, { mean: number; ci_low: number; ci_high: number }>> = {}

  for (const [, entry] of Object.entries(metrics)) {
    if (entry.metric_name !== 'recall' || entry.k === 0) continue
    const seriesKey = `${entry.pipeline_id} / stage${entry.stage_index}`
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

  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={chartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="k" label={{ value: 'K', position: 'insideBottomRight', offset: -4 }} tick={{ fontSize: 12 }} />
        <YAxis tickFormatter={(v) => v.toFixed(2)} tick={{ fontSize: 12 }} domain={[0, 1]} />
        <Tooltip formatter={(v: number) => v.toFixed(4)} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {seriesKeys.map((sk, i) => (
          <Line
            key={sk}
            type="monotone"
            dataKey={sk}
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={2}
            dot={{ r: 4 }}
            activeDot={{ r: 6 }}
          >
            <ErrorBar dataKey={`${sk}_err`} width={4} strokeWidth={1.5} stroke={COLORS[i % COLORS.length]} direction="y" />
          </Line>
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
