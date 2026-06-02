import { useMemo, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ErrorBar, ReferenceLine,
} from 'recharts'
import { MetricsMap } from '../api'
import { fmtQuality } from '../utils/format'
import { buildPipelineColorMap, collectPipelineIds, getPipelineColor } from '../utils/chartColors'
import { buildRecallSeries } from '../utils/pipelineStages'
import { useChartZoom } from '../hooks/useChartZoom'
import { ChartModal } from './ChartModal'
import ChartFrame from './ChartFrame'
import ChartZoomControls from './ChartZoomControls'
import ChartZoomSurface from './ChartZoomSurface'

interface Props {
  metrics: MetricsMap
  baselines?: Record<string, number>
}

export default function RecallCurve({ metrics, baselines = {} }: Props) {
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set())
  const [showIntermediateStages, setShowIntermediateStages] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const { domain: yDomain, fitToData, reset, handleWheel, handlePinchScale, isZoomed } = useChartZoom({
    initialDomain: [0, 1],
    clampZeroOne: false,
  })

  const toggleSeries = (dataKey: string) => {
    setHiddenSeries((prev) => {
      const next = new Set(prev)
      next.has(dataKey) ? next.delete(dataKey) : next.add(dataKey)
      return next
    })
  }

  const { seriesMap, seriesPipelineId, seriesKeys } = useMemo(() => {
    const points = buildRecallSeries(metrics, { showIntermediateStages })
    const map: Record<string, Record<number, { mean: number; ci_low: number; ci_high: number }>> = {}
    const pipelineBySeries: Record<string, string> = {}

    for (const pt of points) {
      pipelineBySeries[pt.seriesKey] = pt.pipelineId
      if (!map[pt.seriesKey]) map[pt.seriesKey] = {}
      map[pt.seriesKey][pt.k] = { mean: pt.mean, ci_low: pt.ci_low, ci_high: pt.ci_high }
    }

    return {
      seriesMap: map,
      seriesPipelineId: pipelineBySeries,
      seriesKeys: Object.keys(map).sort(),
    }
  }, [metrics, showIntermediateStages])

  const pipelineColorMap = useMemo(
    () => buildPipelineColorMap(collectPipelineIds(metrics)),
    [metrics],
  )

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

  const visibleValues = seriesKeys
    .filter((sk) => !hiddenSeries.has(sk))
    .flatMap((sk) => chartData.map((row) => row[sk]).filter((v) => v != null) as number[])
  const dataMin = visibleValues.length > 0 ? Math.min(...visibleValues) : 0
  const dataMax = visibleValues.length > 0 ? Math.max(...visibleValues) : 1

  const referenceLines: Array<{ k: number; value: number }> = allK
    .map((k) => ({ k, value: baselines[`recall@${k}`] }))
    .filter((r) => r.value !== undefined)

  const renderChart = (height: number) => (
    <ChartFrame height={height}>
      <LineChart data={chartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="k" label={{ value: 'K', position: 'insideBottomRight', offset: -4 }} tick={{ fontSize: 12 }} />
        <YAxis tickFormatter={(v) => v.toFixed(2)} tick={{ fontSize: 12 }} domain={[yDomain[0], yDomain[1]]} />
        <Tooltip formatter={(v: number) => fmtQuality(v)} />
        <Legend
          wrapperStyle={{ fontSize: 12 }}
          onClick={(data: any) => toggleSeries(data.dataKey as string)}
          formatter={(value: any, entry: any) => (
            <span style={{
              opacity: hiddenSeries.has(entry.dataKey ?? '') ? 0.35 : 1,
              cursor: 'pointer',
              textDecoration: hiddenSeries.has(entry.dataKey ?? '') ? 'line-through' : 'none',
            }}>
              {value}
            </span>
          )}
        />
        {seriesKeys.map((sk) => {
          const color = getPipelineColor(seriesPipelineId[sk], pipelineColorMap)
          return (
            <Line
              key={sk}
              type="monotone"
              dataKey={sk}
              hide={hiddenSeries.has(sk)}
              stroke={color}
              strokeWidth={2}
              dot={{ r: 4 }}
              activeDot={{ r: 6 }}
            >
              <ErrorBar dataKey={`${sk}_err`} width={4} strokeWidth={1.5} stroke={color} direction="y" />
            </Line>
          )
        })}
        {referenceLines.map(({ k, value }) => (
          <ReferenceLine
            key={`ref-recall-${k}`}
            y={value}
            stroke="#9ca3af"
            strokeDasharray="6 3"
            label={{ value: `BM25 Ref @${k}: ${value.toFixed(3)}`, position: 'right', fontSize: 10, fill: '#9ca3af' }}
          />
        ))}
      </LineChart>
    </ChartFrame>
  )

  const footer = referenceLines.length > 0 && (
    <p className="text-xs text-gray-400 mt-1">Dashed line: published BM25 (Elasticsearch) baseline from BEIR benchmark.</p>
  )

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <p className="text-xs text-gray-500">
          Final-stage recall per pipeline. Per-stage breakdown is in the Stage Recall Funnel below.
        </p>
        <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showIntermediateStages}
            onChange={(e) => {
              setShowIntermediateStages(e.target.checked)
              setHiddenSeries(new Set())
            }}
            className="rounded border-gray-300"
          />
          Show intermediate stages
        </label>
      </div>
      <ChartZoomControls
        domain={yDomain}
        isZoomed={isZoomed}
        onFit={() => fitToData(dataMin, dataMax)}
        onReset={reset}
        onExpand={() => setExpanded(true)}
      />
      <ChartZoomSurface onWheel={handleWheel} onPinchScale={handlePinchScale}>
        {renderChart(260)}
      </ChartZoomSurface>
      {footer}
      {expanded && (
        <ChartModal title="Recall@K Curves" onClose={() => setExpanded(false)}>
          <ChartZoomControls
            domain={yDomain}
            isZoomed={isZoomed}
            onFit={() => fitToData(dataMin, dataMax)}
            onReset={reset}
            compact={false}
          />
          <ChartZoomSurface onWheel={handleWheel} onPinchScale={handlePinchScale}>
            {renderChart(480)}
          </ChartZoomSurface>
          {footer}
        </ChartModal>
      )}
    </div>
  )
}
