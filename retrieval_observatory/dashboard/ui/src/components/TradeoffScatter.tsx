import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Label, Cell, ReferenceLine, ReferenceArea, Customized,
} from 'recharts'
import { fetchParetoFrontier, ParetoFrontierResponse, ParetoPipelineEntry } from '../api'
import { MetricTooltip } from './MetricTooltip'
import { fmtQuality, fmtLatencyMs, fmtCost } from '../utils/format'
import { ChartModal } from './ChartModal'

interface Props {
  runId: string
  latencyBudgetMs?: number
}

const COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#ec4899']

interface ChartPoint {
  pipelineId: string
  label: string
  latencyP50: number
  ndcg10: number
  recall10: number
  latencyP95: number
  costPer1k: number | null
  isParetoOptimal: boolean
  dominatedBy: string[]
}

function toChartPoint(entry: ParetoPipelineEntry): ChartPoint {
  return {
    pipelineId: entry.pipeline_id,
    label: entry.label,
    latencyP50: entry.metrics.latency_p50,
    ndcg10: entry.metrics['ndcg@10'],
    recall10: entry.metrics['recall@10'],
    latencyP95: entry.metrics.latency_p95,
    costPer1k: entry.metrics.cost_per_1k,
    isParetoOptimal: entry.is_pareto_optimal,
    dominatedBy: entry.dominated_by,
  }
}

export default function TradeoffScatter({ runId, latencyBudgetMs }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [frontier, setFrontier] = useState<ParetoFrontierResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [sizeByCost, setSizeByCost] = useState(true)
  const [refAreaLeft, setRefAreaLeft] = useState<number | null>(null)
  const [refAreaRight, setRefAreaRight] = useState<number | null>(null)
  const [isSelecting, setIsSelecting] = useState(false)
  const [xDomain, setXDomain] = useState<[number | 'auto', number | 'auto']>(['auto', 'auto'])
  const [yDomain, setYDomain] = useState<[number, number]>([0, 1])
  const isYZoomed = yDomain[0] !== 0 || yDomain[1] !== 1

  useEffect(() => {
    setFrontier(null)
    setLoadError(null)
    fetchParetoFrontier(runId)
      .then(setFrontier)
      .catch((e) => setLoadError(e.message))
  }, [runId])

  const points = useMemo(
    () => (frontier?.pipelines ?? []).map(toChartPoint),
    [frontier]
  )

  const frontierPoints = useMemo(() => {
    if (!frontier) return []
    const byId = new Map(points.map((p) => [p.pipelineId, p]))
    return frontier.frontier_order
      .map((id) => byId.get(id))
      .filter((p): p is ChartPoint => p != null)
  }, [frontier, points])

  const maxCost = useMemo(() => {
    const costs = points.map((p) => p.costPer1k ?? 0).filter((c) => c > 0)
    return costs.length > 0 ? Math.max(...costs, 0.001) : 1
  }, [points])

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

  if (loadError) {
    return <p className="text-sm text-red-500">Failed to load tradeoff chart: {loadError}</p>
  }

  if (!frontier) {
    return <p className="text-sm text-gray-400">Loading tradeoff chart…</p>
  }

  if (points.length < 2) {
    return (
      <p className="text-sm text-gray-400">
        Tradeoff chart requires at least 2 pipeline configurations with latency and NDCG@10 data.
      </p>
    )
  }

  const showCostSizing = sizeByCost && frontier.cost_included

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

  const budgetMs = latencyBudgetMs ?? frontier.latency_budget_ms ?? undefined

  const CustomDot = (props: any) => {
    const { cx, cy, index } = props
    const pt = points[index]
    const color = COLORS[index % COLORS.length]
    const cost = pt.costPer1k ?? 0
    const r = showCostSizing && cost > 0 ? 5 + (cost / maxCost) * 9 : 7
    return (
      <g>
        <circle cx={cx} cy={cy} r={r} fill={color} fillOpacity={0.85} stroke="white" strokeWidth={1.5} />
        {pt.isParetoOptimal && (
          <circle cx={cx} cy={cy} r={r + 3} fill="none" stroke={color} strokeWidth={1.5} strokeDasharray="3 2" opacity={0.6} />
        )}
      </g>
    )
  }

  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null
    const pt = payload[0].payload as ChartPoint
    return (
      <div className="bg-white border border-gray-200 rounded shadow p-2 text-xs max-w-xs">
        <p className="font-semibold mb-1">{pt.label}</p>
        <p>NDCG@10: <span className="font-mono">{fmtQuality(pt.ndcg10)}</span></p>
        <p>Recall@10: <span className="font-mono">{fmtQuality(pt.recall10)}</span></p>
        <p>P50 Latency: <span className="font-mono">{fmtLatencyMs(pt.latencyP50)} ms</span></p>
        <p>P95 Latency: <span className="font-mono">{fmtLatencyMs(pt.latencyP95)} ms</span></p>
        {pt.costPer1k != null && pt.costPer1k > 0 && (
          <p>Cost / 1k queries: <span className="font-mono">{fmtCost(pt.costPer1k)}</span></p>
        )}
        {pt.isParetoOptimal ? (
          <p className="text-indigo-600 font-semibold mt-1">Pareto optimal</p>
        ) : pt.dominatedBy.length > 0 ? (
          <p className="text-gray-600 mt-1">Dominated by: {pt.dominatedBy.join(', ')}</p>
        ) : null}
      </div>
    )
  }

  const ParetoLine = (props: any) => {
    if (frontierPoints.length < 2) return null
    const xAxisId = Object.keys(props.xAxisMap ?? {})[0]
    const yAxisId = Object.keys(props.yAxisMap ?? {})[0]
    const xScale = props.xAxisMap?.[xAxisId]?.scale
    const yScale = props.yAxisMap?.[yAxisId]?.scale
    if (!xScale || !yScale) return null

    let d = `M ${xScale(frontierPoints[0].latencyP50)} ${yScale(frontierPoints[0].ndcg10)}`
    for (let i = 1; i < frontierPoints.length; i++) {
      const px = xScale(frontierPoints[i].latencyP50)
      const py = yScale(frontierPoints[i].ndcg10)
      const prevY = yScale(frontierPoints[i - 1].ndcg10)
      d += ` L ${px} ${prevY} L ${px} ${py}`
    }

    return (
      <path
        d={d}
        fill="none"
        stroke="#6366f1"
        strokeWidth={1.5}
        strokeDasharray="6 3"
        opacity={0.55}
      />
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
          {budgetMs != null && (
            <ReferenceLine
              x={budgetMs}
              stroke="#ef4444"
              strokeDasharray="5 4"
              label={{ value: `Budget: ${fmtLatencyMs(budgetMs)}ms`, position: 'top', fontSize: 10, fill: '#ef4444' }}
            />
          )}
          {isSelecting && refAreaLeft != null && refAreaRight != null && (
            <ReferenceArea x1={refAreaLeft} x2={refAreaRight} strokeOpacity={0.3} fill="#6366f1" fillOpacity={0.1} />
          )}
          <Customized component={ParetoLine} />
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
        <div key={pt.pipelineId} className="flex items-center gap-1.5 text-xs text-gray-600">
          <span className="inline-block w-3 h-3 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
          {pt.label}
          {pt.isParetoOptimal && <span className="text-indigo-500 font-semibold">★</span>}
        </div>
      ))}
    </div>
  )

  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">
        Each point is one pipeline configuration (final stage). Top-left = best (high quality, low latency).{' '}
        <span className="text-indigo-600 font-medium">- - -</span> Dashed step-line = multi-objective Pareto frontier.{' '}
        {frontier.cost_included && showCostSizing && 'Bubble size = estimated cost per 1k queries. '}
        <span className="font-medium text-indigo-500">★</span> = Pareto-optimal. Drag to zoom X. Ctrl+scroll to zoom Y.
        <MetricTooltip text="Multi-objective Pareto chart across NDCG@10, Recall@10, latency, and cost (when configured). A pipeline is Pareto-optimal if no other pipeline is simultaneously better on all objectives. The dashed step-line connects optimal points in latency order — no smooth curve, because intermediate configs do not exist." />
      </p>
      {frontier.cost_included && (
        <label className="flex items-center gap-2 text-xs text-gray-600 mb-2">
          <input
            type="checkbox"
            checked={sizeByCost}
            onChange={(e) => setSizeByCost(e.target.checked)}
            className="rounded border-gray-300"
          />
          Size by cost
        </label>
      )}
      {!frontier.cost_included && frontier.cost_excluded_reason && (
        <p className="text-xs text-gray-400 mb-2">{frontier.cost_excluded_reason}</p>
      )}
      <div className="flex justify-end mb-1">
        <button
          onClick={() => setExpanded(true)}
          className="text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded px-2 py-0.5"
        >
          Expand ⤢
        </button>
      </div>
      <div onWheel={handleWheel} style={{ touchAction: 'none' }}>
        {renderChart(300)}
      </div>
      {legend}
      {expanded && (
        <ChartModal title="Quality–Latency–Cost Tradeoff" onClose={() => setExpanded(false)}>
          <div onWheel={handleWheel} style={{ touchAction: 'none' }}>
            {renderChart(540)}
          </div>
          {legend}
        </ChartModal>
      )}
    </div>
  )
}
