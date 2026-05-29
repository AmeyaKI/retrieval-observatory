import { useCallback, useState } from 'react'
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Label, Cell, ReferenceLine, ReferenceArea,
} from 'recharts'
import { MetricsMap } from '../api'
import { formatSeriesKey } from '../utils/formatMetricKey'
import { MetricTooltip } from './MetricTooltip'
import { fmtQuality, fmtLatencyMs } from '../utils/format'
import { ChartModal } from './ChartModal'

interface Props {
  metrics: MetricsMap
  latencyBudgetMs?: number
}

const COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#ec4899']

interface Point {
  pipelineId: string
  stageIndex: number
  label: string
  latencyP50: number | null
  ndcg10: number | null
}

export default function TradeoffScatter({ metrics, latencyBudgetMs }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [refAreaLeft, setRefAreaLeft] = useState<number | null>(null)
  const [refAreaRight, setRefAreaRight] = useState<number | null>(null)
  const [isSelecting, setIsSelecting] = useState(false)
  const [xDomain, setXDomain] = useState<[number | 'auto', number | 'auto']>(['auto', 'auto'])
  const [yDomain, setYDomain] = useState<[number, number]>([0, 1])
  const isYZoomed = yDomain[0] !== 0 || yDomain[1] !== 1

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

  const handleMouseDown = (e: any) => {
    if (e?.activePayload?.[0]) {
      const x = e.activePayload[0].payload?.latencyP50
      if (x != null) { setRefAreaLeft(x); setIsSelecting(true) }
    }
  }
  const handleMouseMove = (e: any) => {
    if (!isSelecting) return
    if (e?.activePayload?.[0]) {
      const x = e.activePayload[0].payload?.latencyP50
      if (x != null) setRefAreaRight(x)
    }
  }
  const handleMouseUp = () => {
    if (refAreaLeft != null && refAreaRight != null && refAreaLeft !== refAreaRight) {
      const [l, r] = [Math.min(refAreaLeft, refAreaRight), Math.max(refAreaLeft, refAreaRight)]
      setXDomain([l, r])
    }
    setRefAreaLeft(null)
    setRefAreaRight(null)
    setIsSelecting(false)
  }
  const resetZoom = () => { setXDomain(['auto', 'auto']); setYDomain([0, 1]) }
  const isZoomed = xDomain[0] !== 'auto' || isYZoomed

  const CustomDot = (props: any) => {
    const { cx, cy, index } = props
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
        <p>NDCG@10: <span className="font-mono">{fmtQuality(pt.ndcg10!)}</span></p>
        <p>P50 Latency: <span className="font-mono">{fmtLatencyMs(pt.latencyP50!)} ms</span></p>
      </div>
    )
  }

  const renderChart = (height: number) => (
    <>
      {isZoomed && (
        <div className="flex justify-end mb-1">
          <button onClick={resetZoom} className="text-xs text-indigo-600 hover:text-indigo-800 border border-indigo-200 rounded px-2 py-0.5">
            Reset zoom
          </button>
        </div>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart
          margin={{ top: 10, right: 30, bottom: 30, left: 10 }}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            type="number"
            dataKey="latencyP50"
            name="P50 Latency"
            domain={xDomain}
            tick={{ fontSize: 11 }}
            tickFormatter={(v) => `${fmtLatencyMs(v)}ms`}
          >
            <Label value="P50 Latency (ms)" offset={-12} position="insideBottom" style={{ fontSize: 11, fill: '#6b7280' }} />
          </XAxis>
          <YAxis
            type="number"
            dataKey="ndcg10"
            name="NDCG@10"
            domain={[yDomain[0], yDomain[1]]}
            tick={{ fontSize: 11 }}
            tickFormatter={(v) => fmtQuality(v)}
          >
            <Label value="NDCG@10" angle={-90} position="insideLeft" style={{ fontSize: 11, fill: '#6b7280' }} />
          </YAxis>
          <Tooltip content={<CustomTooltip />} />
          {latencyBudgetMs != null && (
            <ReferenceLine
              x={latencyBudgetMs}
              stroke="#ef4444"
              strokeDasharray="5 4"
              label={{ value: `Budget: ${fmtLatencyMs(latencyBudgetMs)}ms`, position: 'top', fontSize: 10, fill: '#ef4444' }}
            />
          )}
          {isSelecting && refAreaLeft != null && refAreaRight != null && (
            <ReferenceArea x1={refAreaLeft} x2={refAreaRight} strokeOpacity={0.3} fill="#6366f1" fillOpacity={0.1} />
          )}
          <Scatter data={points} shape={<CustomDot />}>
            {points.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </>
  )

  const legend = (
    <div className="flex flex-wrap gap-3 mt-1 justify-center">
      {points.map((pt, i) => (
        <div key={pt.label} className="flex items-center gap-1.5 text-xs text-gray-600">
          <span className="inline-block w-3 h-3 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
          {pt.label}
        </div>
      ))}
    </div>
  )

  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">
        Each point is one pipeline / stage. Top-left = best (high quality, low latency). Drag to zoom X-axis. Pinch to zoom Y-axis.
        <MetricTooltip text="Quality-Latency Pareto chart. The ideal point is top-left: maximum NDCG@10 at minimum P50 latency. Use this to decide whether the latency cost of adding a reranker is justified by the quality gain." />
      </p>
      <div className="flex justify-end mb-1">
        <button
          onClick={() => setExpanded(true)}
          className="text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded px-2 py-0.5"
        >
          Expand ⤢
        </button>
      </div>
      <div onWheel={handleWheel} style={{ touchAction: 'none' }}>
        {renderChart(280)}
      </div>
      {legend}
      {expanded && (
        <ChartModal title="Quality vs. Latency Tradeoff" onClose={() => setExpanded(false)}>
          <div onWheel={handleWheel} style={{ touchAction: 'none' }}>
            {renderChart(520)}
          </div>
          {legend}
        </ChartModal>
      )}
    </div>
  )
}
