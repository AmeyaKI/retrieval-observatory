import { useMemo, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ErrorBar, ReferenceLine,
} from 'recharts'
import { MetricsMap } from '../api'
import { formatSeriesKey } from '../utils/formatMetricKey'
import { fmtQuality } from '../utils/format'
import { buildPipelineColorMap, collectPipelineIds, getPipelineColor } from '../utils/chartColors'
import { useChartZoom } from '../hooks/useChartZoom'
import { ChartModal } from './ChartModal'
import ChartFrame from './ChartFrame'
import ChartZoomControls from './ChartZoomControls'

interface Props {
  metrics: MetricsMap
  baselines?: Record<string, number>
}

export default function RecallCurve({ metrics, baselines = {} }: Props) {
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState(false)
  const { domain: yDomain, zoomIn, zoomOut, fitToData, reset, handleWheel, isZoomed } = useChartZoom({
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

  const seriesMap: Record<string, Record<number, { mean: number; ci_low: number; ci_high: number }>> = {}
  const seriesPipelineId: Record<string, string> = {}
  const pipelineMaxStage: Record<string, number> = {}

  for (const [, entry] of Object.entries(metrics)) {
    if (entry.metric_name !== 'recall' || entry.k === 0 || entry.stage_index < 0) continue
    pipelineMaxStage[entry.pipeline_id] = Math.max(
      pipelineMaxStage[entry.pipeline_id] ?? 0,
      entry.stage_index,
    )
  }

  for (const [, entry] of Object.entries(metrics)) {
    if (entry.metric_name !== 'recall' || entry.k === 0 || entry.stage_index < 0) continue
    const isMultiStage = (pipelineMaxStage[entry.pipeline_id] ?? 0) > 0
    const seriesKey = formatSeriesKey(entry.pipeline_id, entry.stage_index, isMultiStage)
    seriesPipelineId[seriesKey] = entry.pipeline_id
    if (!seriesMap[seriesKey]) seriesMap[seriesKey] = {}
    seriesMap[seriesKey][entry.k] = { mean: entry.mean, ci_low: entry.ci_low, ci_high: entry.ci_high }
  }

  const seriesKeys = Object.keys(seriesMap).sort()
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
      <ChartZoomControls
        domain={yDomain}
        isZoomed={isZoomed}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onFit={() => fitToData(dataMin, dataMax)}
        onReset={reset}
        onExpand={() => setExpanded(true)}
      />
      <div onWheel={handleWheel} style={{ touchAction: 'none' }}>
        {renderChart(260)}
      </div>
      {footer}
      {expanded && (
        <ChartModal title="Recall@K Curves" onClose={() => setExpanded(false)}>
          <ChartZoomControls
            domain={yDomain}
            isZoomed={isZoomed}
            onZoomIn={zoomIn}
            onZoomOut={zoomOut}
            onFit={() => fitToData(dataMin, dataMax)}
            onReset={reset}
            compact={false}
          />
          <div onWheel={handleWheel} style={{ touchAction: 'none' }}>
            {renderChart(480)}
          </div>
          {footer}
        </ChartModal>
      )}
    </div>
  )
}
