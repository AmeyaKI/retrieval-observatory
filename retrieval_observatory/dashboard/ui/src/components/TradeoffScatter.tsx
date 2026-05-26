import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Label, Cell,
} from 'recharts'
import { MetricsMap } from '../api'
import { formatSeriesKey } from '../utils/formatMetricKey'
import { MetricTooltip } from './MetricTooltip'

interface Props {
  metrics: MetricsMap
}

const COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#ec4899']

interface Point {
  pipelineId: string
  stageIndex: number
  label: string
  latencyP50: number | null
  ndcg10: number | null
}

export default function TradeoffScatter({ metrics }: Props) {
  const pointMap = new Map<string, Point>()
  const pipelineMaxStage: Record<string, number> = {}

  for (const [, entry] of Object.entries(metrics)) {
    if (entry.stage_index < 0) continue
    pipelineMaxStage[entry.pipeline_id] = Math.max(
      pipelineMaxStage[entry.pipeline_id] ?? 0,
      entry.stage_index
    )
  }

  for (const [, entry] of Object.entries(metrics)) {
    if (entry.stage_index < 0) continue
    const key = `${entry.pipeline_id}|||${entry.stage_index}`
    const isMultiStage = (pipelineMaxStage[entry.pipeline_id] ?? 0) > 0
    if (!pointMap.has(key)) {
      pointMap.set(key, {
        pipelineId: entry.pipeline_id,
        stageIndex: entry.stage_index,
        label: formatSeriesKey(entry.pipeline_id, entry.stage_index, isMultiStage),
        latencyP50: null,
        ndcg10: null,
      })
    }
    const pt = pointMap.get(key)!
    if (entry.metric_name === 'latency_p50') pt.latencyP50 = entry.mean
    if (entry.metric_name === 'ndcg' && entry.k === 10) pt.ndcg10 = entry.mean
  }

  const points = [...pointMap.values()].filter((p) => p.latencyP50 != null && p.ndcg10 != null)

  if (points.length < 2) {
    return (
      <p className="text-sm text-gray-400">
        Tradeoff chart requires at least 2 pipeline/stage combinations with latency and NDCG@10 data.
      </p>
    )
  }

  const CustomDot = (props: any) => {
    const { cx, cy, payload, index } = props
    const color = COLORS[index % COLORS.length]
    return (
      <g>
        <circle cx={cx} cy={cy} r={7} fill={color} fillOpacity={0.85} stroke="white" strokeWidth={1.5} />
      </g>
    )
  }

  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null
    const pt = payload[0].payload as Point
    return (
      <div className="bg-white border border-gray-200 rounded shadow p-2 text-xs">
        <p className="font-semibold mb-1">{pt.label}</p>
        <p>NDCG@10: <span className="font-mono">{pt.ndcg10!.toFixed(4)}</span></p>
        <p>P50 Latency: <span className="font-mono">{pt.latencyP50!.toFixed(1)} ms</span></p>
      </div>
    )
  }

  // Custom legend below chart
  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">
        Each point is one pipeline / stage. Top-left = best (high quality, low latency).
        <MetricTooltip text="Quality-Latency Pareto chart. The ideal point is top-left: maximum NDCG@10 at minimum P50 latency. Use this to decide whether the latency cost of adding a reranker is justified by the quality gain." />
      </p>
      <ResponsiveContainer width="100%" height={280}>
        <ScatterChart margin={{ top: 10, right: 30, bottom: 30, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            type="number"
            dataKey="latencyP50"
            name="P50 Latency"
            tick={{ fontSize: 11 }}
            tickFormatter={(v) => `${v.toFixed(0)}ms`}
          >
            <Label value="P50 Latency (ms)" offset={-12} position="insideBottom" style={{ fontSize: 11, fill: '#6b7280' }} />
          </XAxis>
          <YAxis
            type="number"
            dataKey="ndcg10"
            name="NDCG@10"
            domain={['auto', 'auto']}
            tick={{ fontSize: 11 }}
            tickFormatter={(v) => v.toFixed(3)}
          >
            <Label value="NDCG@10" angle={-90} position="insideLeft" style={{ fontSize: 11, fill: '#6b7280' }} />
          </YAxis>
          <Tooltip content={<CustomTooltip />} />
          <Scatter data={points} shape={<CustomDot />}>
            {points.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
      <div className="flex flex-wrap gap-3 mt-1 justify-center">
        {points.map((pt, i) => (
          <div key={pt.label} className="flex items-center gap-1.5 text-xs text-gray-600">
            <span
              className="inline-block w-3 h-3 rounded-full"
              style={{ backgroundColor: COLORS[i % COLORS.length] }}
            />
            {pt.label}
          </div>
        ))}
      </div>
    </div>
  )
}
