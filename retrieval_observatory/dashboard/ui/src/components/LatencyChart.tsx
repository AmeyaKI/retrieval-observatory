import { useMemo, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend,
} from 'recharts'
import { MetricsMap } from '../api'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'
import { fmtLatencyMs } from '../utils/format'
import {
  detectLatencyPercentiles,
  LATENCY_PERCENTILE_SERIES,
  type LatencyPercentileSeries,
} from '../utils/chartColors'
import { useChartZoom } from '../hooks/useChartZoom'
import { ChartModal } from './ChartModal'
import ChartFrame from './ChartFrame'
import ChartZoomControls from './ChartZoomControls'

interface Props {
  metrics: MetricsMap
}

interface LatencyRow {
  pipelineId: string
  stageIndex: number
  label: string
  isTotal: boolean
  p50: number | null
  p95: number | null
  p99: number | null
}

// Abbreviate one stage part of a pipeline ID: "fast_rerank" → "FR", "bm25" → "BM25"
function stageAbbrev(part: string): string {
  const known: Record<string, string> = { bm25: 'BM25', dense: 'DN', rrf: 'RRF' }
  return known[part] ?? part.split('_').map((w) => w[0].toUpperCase()).join('')
}

// Human-readable stage name: "fast_rerank" → "Fast Reranker", "bm25" → "BM25"
function stageDisplayName(part: string): string {
  const known: Record<string, string> = { bm25: 'BM25', dense: 'Dense Retriever', rrf: 'RRF Fusion' }
  if (known[part]) return known[part]
  return part
    .replace(/_rerank$/, ' Reranker')
    .replace(/_retriever$/, ' Retriever')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

// "bm25__fast_rerank__precise_rerank" → "BM25+FR+PR"
function pipelineAbbrev(pipelineId: string): string {
  return pipelineId.split('__').map(stageAbbrev).join('+')
}

// Unique bar label: "BM25+FR+PR · Fast Reranker" or just "BM25" for single-stage
function barLabel(pipelineId: string, stageIndex: number, isMulti: boolean): string {
  const parts = pipelineId.split('__')
  const name = stageDisplayName(parts[stageIndex] ?? '')
  return isMulti ? `${pipelineAbbrev(pipelineId)} · ${name}` : name
}

function buildLatencyGroups(metrics: MetricsMap): Record<string, Record<string, number>> {
  const groups: Record<string, Record<string, number>> = {}
  for (const entry of Object.values(metrics)) {
    if (!entry.metric_name.startsWith('latency_p')) continue
    const key = `${entry.pipeline_id}|||${entry.stage_index}`
    if (!groups[key]) groups[key] = {}
    groups[key][entry.metric_name] = entry.mean
  }
  return groups
}

function buildPipelineMaxStage(metrics: MetricsMap): Record<string, number> {
  const maxStage: Record<string, number> = {}
  for (const entry of Object.values(metrics)) {
    if (entry.stage_index >= 0) {
      maxStage[entry.pipeline_id] = Math.max(maxStage[entry.pipeline_id] ?? 0, entry.stage_index)
    }
  }
  return maxStage
}

function rowFromGroup(
  rawKey: string,
  groups: Record<string, Record<string, number>>,
  opts: { isTotal: boolean; isMultiStage: (id: string) => boolean },
): LatencyRow {
  const [pipelineId, stageStr] = rawKey.split('|||')
  const stageIndex = parseInt(stageStr, 10)
  const g = groups[rawKey]
  return {
    pipelineId,
    stageIndex,
    label: opts.isTotal
      ? `${pipelineAbbrev(pipelineId)} · E2E Total`
      : barLabel(pipelineId, stageIndex, opts.isMultiStage(pipelineId)),
    isTotal: opts.isTotal,
    p50: g.latency_p50 ?? null,
    p95: g.latency_p95 ?? null,
    p99: g.latency_p99 ?? null,
  }
}

function LatencyTooltip({
  active,
  payload,
  label,
  percentileSeries,
}: {
  active?: boolean
  payload?: Array<{ dataKey: string; value: number; color: string }>
  label?: string
  percentileSeries: LatencyPercentileSeries[]
}) {
  if (!active || !payload?.length) return null
  const byKey = Object.fromEntries(percentileSeries.map((s) => [s.dataKey, s.label]))
  return (
    <div className="bg-white border border-gray-200 rounded shadow p-2 text-xs">
      <p className="font-semibold mb-1">{label}</p>
      {payload
        .filter((p) => p.value != null)
        .map((p) => (
          <p key={p.dataKey} style={{ color: p.color }}>
            {byKey[p.dataKey] ?? p.dataKey}: {fmtLatencyMs(p.value)} ms
          </p>
        ))}
    </div>
  )
}

export default function LatencyChart({ metrics }: Props) {
  const [expanded, setExpanded] = useState(false)
  const { domain: yDomain, zoomIn, zoomOut, fitToData, reset, handleWheel, isZoomed } = useChartZoom({
    initialDomain: [0, 1],
    clampZeroOne: false,
  })

  const percentileSeries = useMemo(() => detectLatencyPercentiles(metrics), [metrics])

  const { chartData, totalRowCount } = useMemo(() => {
    const groups = buildLatencyGroups(metrics)
    const groupKeys = Object.keys(groups)
    const pipelineMaxStage = buildPipelineMaxStage(metrics)
    const isMultiStage = (pipelineId: string) => (pipelineMaxStage[pipelineId] ?? 0) > 0

    const perStageData = groupKeys
      .filter((k) => parseInt(k.split('|||')[1], 10) >= 0)
      .sort((a, b) => {
        const [pa, sa] = a.split('|||')
        const [pb, sb] = b.split('|||')
        const cmp = pa.localeCompare(pb)
        return cmp !== 0 ? cmp : parseInt(sa, 10) - parseInt(sb, 10)
      })
      .map((rawKey) => rowFromGroup(rawKey, groups, { isTotal: false, isMultiStage }))

    const totalRows = groupKeys
      .filter((k) => parseInt(k.split('|||')[1], 10) === -1)
      .sort((a, b) => a.localeCompare(b))
      .map((rawKey) => rowFromGroup(rawKey, groups, { isTotal: true, isMultiStage }))

    return { chartData: [...perStageData, ...totalRows], totalRowCount: totalRows.length }
  }, [metrics])

  if (chartData.length === 0 || percentileSeries.length === 0) {
    return <p className="text-sm text-gray-400">No latency data.</p>
  }

  const latencyMax = useMemo(() => {
    const values: number[] = []
    for (const row of chartData) {
      for (const s of percentileSeries) {
        const v = row[s.dataKey]
        if (v != null) values.push(v)
      }
    }
    return Math.max(...values, 1)
  }, [chartData, percentileSeries])

  const yMax = isZoomed ? yDomain[1] * latencyMax : undefined
  const yMin = isZoomed ? yDomain[0] * latencyMax : 0

  const missingP99 = !percentileSeries.some((s) => s.dataKey === 'p99')
    && LATENCY_PERCENTILE_SERIES.some((s) => s.dataKey === 'p99')

  const note = (
    <p className="text-xs text-gray-500 mb-2">
      Grouped bars use fixed colors per percentile (P50 / P95 / P99). Each x-axis label is a pipeline stage.
      <MetricTooltip text={`${METRIC_GLOSSARY.latency_p50}\n\n${METRIC_GLOSSARY.latency_p95}\n\n${METRIC_GLOSSARY.latency_p99}`} />
      {totalRowCount > 0 && (
        <span className="ml-2 text-gray-400">· &quot;E2E Total&quot; = end-to-end percentiles on per-query total latency</span>
      )}
      {missingP99 && (
        <span className="ml-2 text-gray-400">· P99 not collected in this run</span>
      )}
    </p>
  )

  const renderChart = (height: number) => (
    <ChartFrame height={height}>
      <BarChart data={chartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="label" tick={{ fontSize: 11 }} interval={0} angle={chartData.length > 5 ? -20 : 0} textAnchor={chartData.length > 5 ? 'end' : 'middle'} height={chartData.length > 5 ? 56 : 30} />
        <YAxis tickFormatter={(v) => `${fmtLatencyMs(v)}ms`} tick={{ fontSize: 11 }} domain={[yMin, yMax ?? 'auto']} />
        <Tooltip content={<LatencyTooltip percentileSeries={percentileSeries} />} />
        <Legend
          wrapperStyle={{ fontSize: 12 }}
          formatter={(value: string, entry: { color?: string }) => (
            <span style={{ color: entry.color ?? '#374151' }}>{value}</span>
          )}
        />
        {percentileSeries.map((series) => (
          <Bar
            key={series.dataKey}
            dataKey={series.dataKey}
            name={series.label}
            fill={series.color}
            radius={[3, 3, 0, 0]}
          />
        ))}
      </BarChart>
    </ChartFrame>
  )

  return (
    <div>
      {note}
      <ChartZoomControls
        domain={yDomain}
        isZoomed={isZoomed}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onFit={() => fitToData(0, latencyMax, 0.05)}
        onReset={reset}
        onExpand={() => setExpanded(true)}
      />
      <div onWheel={handleWheel} style={{ touchAction: 'none' }}>
        {renderChart(260)}
      </div>
      {expanded && (
        <ChartModal title="Latency Percentiles" onClose={() => setExpanded(false)}>
          {note}
          <ChartZoomControls
            domain={yDomain}
            isZoomed={isZoomed}
            onZoomIn={zoomIn}
            onZoomOut={zoomOut}
            onFit={() => fitToData(0, latencyMax, 0.05)}
            onReset={reset}
            compact={false}
          />
          <div onWheel={handleWheel} style={{ touchAction: 'none' }}>
            {renderChart(500)}
          </div>
        </ChartModal>
      )}
    </div>
  )
}
