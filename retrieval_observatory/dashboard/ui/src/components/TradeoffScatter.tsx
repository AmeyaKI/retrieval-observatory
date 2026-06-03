import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  Label, ReferenceLine, ReferenceArea, Customized,
} from 'recharts'
import { fetchParetoFrontier, ParetoFrontierResponse, ParetoPipelineEntry } from '../api'
import { MetricTooltip } from './MetricTooltip'
import { fmtQuality, fmtLatencyMs, fmtCost } from '../utils/format'
import { buildPipelineColorMap, getPipelineColor } from '../utils/chartColors'
import { isZoomWheelEvent, useChartZoom, useNumericZoom, wheelDeltaToZoomFactor, pinchScaleToZoomFactor } from '../hooks/useChartZoom'
import { ChartModal } from './ChartModal'
import ChartFrame from './ChartFrame'
import ChartZoomControls from './ChartZoomControls'
import ChartZoomSurface from './ChartZoomSurface'

interface Props {
  runId: string
  latencyBudgetMs?: number
}

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
  const m = entry.metrics
  return {
    pipelineId: entry.pipeline_id,
    label: entry.label,
    latencyP50: m.latency_p50 ?? 0,
    ndcg10: m['ndcg@10'] ?? 0,
    recall10: m['recall@10'] ?? 0,
    latencyP95: m.latency_p95 ?? 0,
    costPer1k: m.cost_per_1k,
    isParetoOptimal: entry.is_pareto_optimal,
    dominatedBy: entry.dominated_by,
  }
}

function TradeoffTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: ChartPoint }> }) {
  if (!active || !payload?.length) return null
  const pt = payload[0].payload
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

function ParetoLineLayer({
  xAxisMap,
  yAxisMap,
  frontierPoints,
}: {
  xAxisMap?: Record<string, { scale?: (v: number) => number }>
  yAxisMap?: Record<string, { scale?: (v: number) => number }>
  frontierPoints: ChartPoint[]
}) {
  if (frontierPoints.length < 2) return null
  const xScale = xAxisMap?.[Object.keys(xAxisMap ?? {})[0] ?? '']?.scale
  const yScale = yAxisMap?.[Object.keys(yAxisMap ?? {})[0] ?? '']?.scale
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
      stroke="#0072B2"
      strokeWidth={2}
      strokeDasharray="6 4"
      opacity={0.75}
    />
  )
}

function starPath(cx: number, cy: number, outerR: number, innerR: number): string {
  const points: string[] = []
  for (let i = 0; i < 10; i += 1) {
    const angle = (Math.PI / 2) + (i * Math.PI) / 5
    const r = i % 2 === 0 ? outerR : innerR
    points.push(`${cx + r * Math.cos(angle)},${cy - r * Math.sin(angle)}`)
  }
  return `M ${points.join(' L ')} Z`
}

function makeDotRenderer(
  color: string,
  showCostSizing: boolean,
  maxCost: number,
) {
  return (props: { cx?: number; cy?: number; payload?: ChartPoint }) => {
    const { cx, cy, payload: pt } = props
    if (!pt || cx == null || cy == null) return null
    const cost = pt.costPer1k ?? 0
    const r = showCostSizing && cost > 0 ? 5 + (cost / maxCost) * 9 : 7
    if (pt.isParetoOptimal) {
      const outer = r + 1
      const inner = outer * 0.42
      return (
        <path
          d={starPath(cx, cy, outer, inner)}
          fill={color}
          fillOpacity={0.9}
          stroke="white"
          strokeWidth={1.5}
        />
      )
    }
    return (
      <circle cx={cx} cy={cy} r={r} fill={color} fillOpacity={0.85} stroke="white" strokeWidth={1.5} />
    )
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

  const {
    domain: yDomain,
    fitToData: fitYToData,
    reset: resetY,
    zoomByFactor: zoomYByFactor,
    isZoomed: isYZoomed,
  } = useChartZoom({
    initialDomain: [0, 1],
    clampZeroOne: false,
  })
  const { xDomain, zoomXByFactor, fitXToData, resetX, isXZoomed } = useNumericZoom()

  useEffect(() => {
    setFrontier(null)
    setLoadError(null)
    fetchParetoFrontier(runId)
      .then(setFrontier)
      .catch((e) => setLoadError(e.message))
  }, [runId])

  const points = useMemo(
    () => (frontier?.pipelines ?? []).map(toChartPoint),
    [frontier],
  )

  const colorMap = useMemo(
    () => buildPipelineColorMap(points.map((p) => p.pipelineId)),
    [points],
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

  const showCostSizing = sizeByCost && !!frontier?.cost_included

  const xMin = points.length > 0 ? Math.min(...points.map((p) => p.latencyP50)) : 0
  const xMax = points.length > 0 ? Math.max(...points.map((p) => p.latencyP50)) : 1
  const yMin = points.length > 0 ? Math.min(...points.map((p) => p.ndcg10)) : 0
  const yMax = points.length > 0 ? Math.max(...points.map((p) => p.ndcg10)) : 1

  const paretoLayer = useCallback(
    (props: { xAxisMap?: Record<string, { scale?: (v: number) => number }>; yAxisMap?: Record<string, { scale?: (v: number) => number }> }) => (
      <ParetoLineLayer {...props} frontierPoints={frontierPoints} />
    ),
    [frontierPoints],
  )

  const applyChartZoomFactor = useCallback(
    (factor: number) => {
      zoomYByFactor(factor)
      zoomXByFactor(factor, xMin, xMax)
    },
    [zoomYByFactor, zoomXByFactor, xMin, xMax],
  )

  const handleChartWheel = useCallback(
    (e: WheelEvent) => {
      if (!isZoomWheelEvent(e)) return
      e.preventDefault()
      e.stopPropagation()
      applyChartZoomFactor(wheelDeltaToZoomFactor(e.deltaY))
    },
    [applyChartZoomFactor],
  )

  const handleChartPinchScale = useCallback(
    (scaleRatio: number) => {
      applyChartZoomFactor(pinchScaleToZoomFactor(scaleRatio))
    },
    [applyChartZoomFactor],
  )

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

  const handleMouseDown = (e: { activePayload?: Array<{ payload?: ChartPoint }> }) => {
    const x = e?.activePayload?.[0]?.payload?.latencyP50
    if (x != null) { setRefAreaLeft(x); setIsSelecting(true) }
  }
  const handleMouseMove = (e: { activePayload?: Array<{ payload?: ChartPoint }> }) => {
    if (!isSelecting) return
    const x = e?.activePayload?.[0]?.payload?.latencyP50
    if (x != null) setRefAreaRight(x)
  }
  const handleMouseUp = () => {
    if (refAreaLeft != null && refAreaRight != null && refAreaLeft !== refAreaRight) {
      const [l, r] = [Math.min(refAreaLeft, refAreaRight), Math.max(refAreaLeft, refAreaRight)]
      fitXToData(l, r)
    }
    setRefAreaLeft(null)
    setRefAreaRight(null)
    setIsSelecting(false)
  }

  const resetZoom = () => { resetX(); resetY() }
  const isZoomed = isXZoomed || isYZoomed
  const budgetMs = latencyBudgetMs ?? frontier.latency_budget_ms ?? undefined

  const renderChart = (height: number) => (
    <ChartFrame height={height}>
      <ScatterChart
        margin={{ top: 18, right: 30, bottom: 30, left: 10 }}
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
        <Tooltip content={<TradeoffTooltip />} />
        {budgetMs != null && (
          <ReferenceLine
            x={budgetMs}
            stroke="#ef4444"
            strokeDasharray="5 4"
            label={{ value: `Budget: ${fmtLatencyMs(budgetMs)}ms`, position: 'top', fontSize: 10, fill: '#ef4444' }}
          />
        )}
        {isSelecting && refAreaLeft != null && refAreaRight != null && (
          <ReferenceArea x1={refAreaLeft} x2={refAreaRight} strokeOpacity={0.3} fill="#0072B2" fillOpacity={0.1} />
        )}
        <Customized component={paretoLayer} />
        {points.map((pt) => {
          const color = getPipelineColor(pt.pipelineId, colorMap)
          return (
            <Scatter
              key={pt.pipelineId}
              name={pt.label}
              data={[pt]}
              fill={color}
              legendType="none"
              shape={makeDotRenderer(color, showCostSizing, maxCost) as (props: unknown) => JSX.Element}
            />
          )
        })}
      </ScatterChart>
    </ChartFrame>
  )

  const paretoOptimalCount = points.filter((p) => p.isParetoOptimal).length

  const legend = (
    <div className="flex flex-wrap gap-x-4 gap-y-2 mt-2 justify-center items-center text-xs text-gray-600">
      {points.map((pt) => {
        const color = getPipelineColor(pt.pipelineId, colorMap)
        return (
          <div key={pt.pipelineId} className="flex items-center gap-1.5">
            {pt.isParetoOptimal ? (
              <svg width={14} height={14} viewBox="0 0 14 14" className="shrink-0" aria-hidden>
                <path d={starPath(7, 7, 6.5, 2.8)} fill={color} stroke="white" strokeWidth={0.75} />
              </svg>
            ) : (
              <span className="inline-block w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: color }} />
            )}
            <span>{pt.label}</span>
          </div>
        )
      })}
      <span className="text-gray-300 hidden sm:inline">|</span>
      <div className="flex items-center gap-1.5 text-gray-500">
        <svg width={12} height={12} viewBox="0 0 14 14" className="shrink-0" aria-hidden>
          <path d={starPath(7, 7, 6, 2.5)} fill="#9ca3af" stroke="#e5e7eb" strokeWidth={0.75} />
        </svg>
        <span>Star = Pareto optimal ({paretoOptimalCount} of {points.length})</span>
      </div>
      {frontierPoints.length >= 2 && (
        <>
          <span className="text-gray-300 hidden sm:inline">|</span>
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-5 border-t-2 border-dashed border-[#0072B2] opacity-70" />
            <span>Pareto frontier (quality–latency step-line)</span>
          </div>
        </>
      )}
    </div>
  )

  const zoomControls = (
    <div className="flex flex-wrap justify-end items-center gap-1.5 mb-1">
      <ChartZoomControls
        domain={yDomain}
        isZoomed={isYZoomed}
        onFit={() => fitYToData(yMin, yMax)}
        onReset={resetY}
        onExpand={() => setExpanded(true)}
      />
      <button type="button" onClick={() => fitXToData(xMin, xMax)} className="text-xs text-gray-500 hover:text-indigo-600 border border-gray-200 rounded px-1.5 py-0.5">Fit X</button>
      {isXZoomed && (
        <button type="button" onClick={resetX} className="text-xs text-indigo-600 border border-indigo-200 rounded px-2 py-0.5">Reset X</button>
      )}
      {isZoomed && (
        <button type="button" onClick={resetZoom} className="text-xs text-indigo-600 border border-indigo-200 rounded px-2 py-0.5">Reset all</button>
      )}
    </div>
  )

  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">
        Each point is one pipeline (final stage). Top-left = best (high NDCG@10, low latency).{' '}
        The dashed step-line connects <strong>Pareto-optimal</strong> pipelines only — dominated configs (e.g. same quality at much higher latency) are omitted from the frontier.{' '}
        A <strong>star</strong> replaces the dot for optimal pipelines (same color as that pipeline). Drag to select an X range; hold ⌘ and pinch or scroll to zoom both axes.
        <MetricTooltip text="A pipeline is Pareto-optimal if no other pipeline is simultaneously better on NDCG@10, Recall@10, and latency (P50 and P95). The frontier step-line links optimal points sorted by latency — it does not pass through dominated pipelines." />
      </p>
      {frontier.cost_included && (
        <label className="flex items-center gap-2 text-xs text-gray-600 mb-2">
          <input type="checkbox" checked={sizeByCost} onChange={(e) => setSizeByCost(e.target.checked)} className="rounded border-gray-300" />
          Size by cost
        </label>
      )}
      {!frontier.cost_included && frontier.cost_excluded_reason && (
        <p className="text-xs text-gray-400 mb-2">{frontier.cost_excluded_reason}</p>
      )}
      {zoomControls}
      <ChartZoomSurface onWheel={handleChartWheel} onPinchScale={handleChartPinchScale}>
        {renderChart(300)}
      </ChartZoomSurface>
      {legend}
      {expanded && (
        <ChartModal title="Quality–Latency Tradeoff" onClose={() => setExpanded(false)}>
          {zoomControls}
          <ChartZoomSurface onWheel={handleChartWheel} onPinchScale={handleChartPinchScale}>
            {renderChart(540)}
          </ChartZoomSurface>
          {legend}
        </ChartModal>
      )}
    </div>
  )
}
