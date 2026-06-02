import { useEffect, useMemo, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts'
import { fetchSegmentMetrics, SegmentMetrics } from '../api'
import { formatSeriesKey } from '../utils/formatMetricKey'
import { fmtQuality } from '../utils/format'
import { buildPipelineColorMap, getPipelineColor } from '../utils/chartColors'
import { useChartZoom } from '../hooks/useChartZoom'
import { ChartModal } from './ChartModal'
import ChartFrame from './ChartFrame'
import ChartZoomControls from './ChartZoomControls'
import ChartZoomSurface from './ChartZoomSurface'

interface Props {
  runId: string
  field?: string
  targetMetric?: string
}

function buildSegmentChart(data: SegmentMetrics, targetMetric: string) {
  const segValues = Object.keys(data.segments).sort((a, b) => {
    const na = Number(a), nb = Number(b)
    return isNaN(na) || isNaN(nb) ? a.localeCompare(b) : na - nb
  })

  const pipelineMaxStage: Record<string, number> = {}
  for (const seg of segValues) {
    for (const mKey of Object.keys(data.segments[seg])) {
      const entry = data.segments[seg][mKey]
      if (entry.metric_name === targetMetric && entry.stage_index >= 0) {
        pipelineMaxStage[entry.pipeline_id] = Math.max(
          pipelineMaxStage[entry.pipeline_id] ?? 0,
          entry.stage_index,
        )
      }
    }
  }

  const seriesKeys = new Set<string>()
  for (const seg of segValues) {
    for (const mKey of Object.keys(data.segments[seg])) {
      const entry = data.segments[seg][mKey]
      if (entry.metric_name !== targetMetric || entry.stage_index < 0) continue
      const finalStage = pipelineMaxStage[entry.pipeline_id] ?? entry.stage_index
      if (entry.stage_index !== finalStage) continue
      seriesKeys.add(`${entry.pipeline_id}|${entry.stage_index}`)
    }
  }

  const isMultiStage = (pipelineId: string) => (pipelineMaxStage[pipelineId] ?? 0) > 0

  const chartData = segValues.map((seg) => {
    const row: Record<string, string | number> = { segment: seg }
    for (const sk of seriesKeys) {
      const [pipelineId, stageStr] = sk.split('|')
      const stageIndex = parseInt(stageStr, 10)
      const entry = Object.values(data.segments[seg]).find(
        (e) => e.pipeline_id === pipelineId && e.stage_index === stageIndex && e.metric_name === targetMetric,
      )
      const label = formatSeriesKey(pipelineId, stageIndex, isMultiStage(pipelineId))
      row[label] = entry ? entry.mean : 0
      if (entry?.n != null) row[`${label}__n`] = entry.n
    }
    return row
  })

  const seriesKeysSorted = [...seriesKeys].sort()
  const seriesLabels = seriesKeysSorted.map((sk) => {
    const [pipelineId, stageStr] = sk.split('|')
    return formatSeriesKey(pipelineId, parseInt(stageStr, 10), isMultiStage(pipelineId))
  })

  const pipelineIds = [...new Set(seriesKeysSorted.map((sk) => sk.split('|')[0]))]

  return { chartData, seriesLabels, segValues, seriesKeysSorted, pipelineIds }
}

export default function SegmentBreakdown({ runId, field = 'n_relevant', targetMetric = 'ndcg' }: Props) {
  const [data, setData] = useState<SegmentMetrics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState(false)
  const { domain: yDomain, fitToData, reset, handleWheel, handlePinchScale, isZoomed } = useChartZoom({
    initialDomain: [0, 1],
    clampZeroOne: false,
  })

  useEffect(() => {
    setData(null)
    setError(null)
    fetchSegmentMetrics(runId, field)
      .then(setData)
      .catch((e) => setError(e.message))
  }, [runId, field])

  const built = useMemo(
    () => (data ? buildSegmentChart(data, targetMetric) : null),
    [data, targetMetric],
  )

  const pipelineColorMap = useMemo(
    () => buildPipelineColorMap(built?.pipelineIds ?? []),
    [built?.pipelineIds.join('|')],
  )

  const visibleValues = useMemo(() => {
    if (!built) return []
    return built.chartData.flatMap((row) =>
      built.seriesLabels
        .filter((l) => !hiddenSeries.has(l))
        .map((l) => row[l] as number)
        .filter((v) => v != null),
    )
  }, [built, hiddenSeries])

  const toggleSeries = (label: string) => {
    setHiddenSeries((prev) => {
      const next = new Set(prev)
      next.has(label) ? next.delete(label) : next.add(label)
      return next
    })
  }

  if (error) return <p className="text-sm text-red-500">{error}</p>

  if (!data || !built) {
    return (
      <div className="flex items-center gap-2 text-gray-400 text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 border-t-indigo-600" />
        Loading segment data...
      </div>
    )
  }

  if (Object.keys(data.segments).length === 0) {
    return <p className="text-sm text-gray-400">No segment data available for field &quot;{field}&quot;.</p>
  }

  if (built.seriesLabels.length === 0) {
    return <p className="text-sm text-gray-400">No &quot;{targetMetric}&quot; metric found in segment data.</p>
  }

  const { chartData, seriesLabels, seriesKeysSorted } = built
  const dataMin = visibleValues.length > 0 ? Math.min(...visibleValues) : 0
  const dataMax = visibleValues.length > 0 ? Math.max(...visibleValues) : 1

  const metricLabel = targetMetric.toUpperCase()
  const xLabel = field === 'n_relevant' ? '# Relevant Docs' : field
  const displayLabel = (label: string) => (label.length > 36 ? `${label.slice(0, 33)}...` : label)

  const SegmentTooltip = ({ active, payload, label }: { active?: boolean; payload?: Array<{ dataKey?: string; value?: number; color?: string }>; label?: string }) => {
    if (!active || !payload?.length) return null
    const row = chartData.find((r) => r.segment === label)
    return (
      <div className="bg-white border border-gray-200 rounded shadow p-2 text-xs">
        <p className="font-semibold mb-1">{field === 'n_relevant' ? `${label} relevant doc(s)` : label}</p>
        {field === 'n_relevant' && (
          <p className="text-gray-500 mb-1">Queries where ground truth has exactly {label} relevant document{label === '1' ? '' : 's'}.</p>
        )}
        {payload.map((p) => {
          const n = row?.[`${p.dataKey}__n`]
          return (
            <p key={p.dataKey} style={{ color: p.color }}>
              {p.dataKey}: {fmtQuality(p.value ?? 0)}{n != null ? ` (n=${n})` : ''}
            </p>
          )
        })}
      </div>
    )
  }

  const renderChart = (height: number) => (
    <ChartFrame height={height}>
      <BarChart data={chartData} margin={{ top: 4, right: 20, bottom: 44, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis
          dataKey="segment"
          tick={{ fontSize: 11 }}
          label={{ value: xLabel, position: 'insideBottom', offset: -14, style: { fontSize: 11, fill: '#6b7280' } }}
        />
        <YAxis tickFormatter={(v: number) => v.toFixed(2)} tick={{ fontSize: 11 }} domain={[yDomain[0], yDomain[1]]} />
        <Tooltip content={<SegmentTooltip />} />
        {seriesLabels.map((label, i) => {
          const pipelineId = seriesKeysSorted[i]?.split('|')[0] ?? ''
          const color = getPipelineColor(pipelineId, pipelineColorMap)
          return (
          <Bar
            key={label}
            dataKey={label}
            hide={hiddenSeries.has(label)}
            fill={color}
            radius={[2, 2, 0, 0]}
          />
          )
        })}
      </BarChart>
    </ChartFrame>
  )

  const legend = (
    <div className="flex flex-wrap gap-3 mt-2 justify-center">
      {seriesLabels.map((label, i) => {
        const pipelineId = seriesKeysSorted[i]?.split('|')[0] ?? ''
        const color = getPipelineColor(pipelineId, pipelineColorMap)
        return (
        <div
          key={label}
          className="flex items-center gap-1.5 text-xs text-gray-600 max-w-[240px] cursor-pointer select-none"
          style={{ opacity: hiddenSeries.has(label) ? 0.35 : 1 }}
          onClick={() => toggleSeries(label)}
        >
          <span className="inline-block w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: color }} />
          <span className="truncate" style={{ textDecoration: hiddenSeries.has(label) ? 'line-through' : 'none' }}>
            {displayLabel(label)}
          </span>
        </div>
        )
      })}
    </div>
  )

  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">
        <strong>X-axis:</strong> number of ground-truth relevant documents per query ({field}).
        <strong className="ml-2">Y-axis:</strong> mean {metricLabel}@10 for queries in that bucket (final stage per pipeline).
        Higher Y = better ranking quality for that query difficulty slice.
      </p>
      <ChartZoomControls
        domain={yDomain}
        isZoomed={isZoomed}
        onFit={() => fitToData(dataMin, dataMax)}
        onReset={reset}
        onExpand={() => setExpanded(true)}
      />
      <ChartZoomSurface onWheel={handleWheel} onPinchScale={handlePinchScale}>
        {renderChart(240)}
      </ChartZoomSurface>
      {legend}
      {expanded && (
        <ChartModal title={`${metricLabel} by ${xLabel}`} onClose={() => setExpanded(false)}>
          <ChartZoomControls domain={yDomain} isZoomed={isZoomed} onFit={() => fitToData(dataMin, dataMax)} onReset={reset} compact={false} />
          <ChartZoomSurface onWheel={handleWheel} onPinchScale={handlePinchScale}>{renderChart(480)}</ChartZoomSurface>
          {legend}
        </ChartModal>
      )}
    </div>
  )
}
