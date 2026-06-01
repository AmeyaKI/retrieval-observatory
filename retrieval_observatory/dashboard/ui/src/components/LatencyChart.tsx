import { useMemo, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, Cell,
} from 'recharts'
import { MetricsMap } from '../api'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'
import { fmtLatencyMs } from '../utils/format'
import { buildPipelineColorMap, collectPipelineIds, getPipelineColor, withAlpha } from '../utils/chartColors'
import { useChartZoom } from '../hooks/useChartZoom'
import { ChartModal } from './ChartModal'
import ChartFrame from './ChartFrame'
import ChartZoomControls from './ChartZoomControls'

interface Props {
  metrics: MetricsMap
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

export default function LatencyChart({ metrics }: Props) {
  const [expanded, setExpanded] = useState(false)
  const { domain: yDomain, zoomIn, zoomOut, fitToData, reset, handleWheel, isZoomed } = useChartZoom({
    initialDomain: [0, 1],
    clampZeroOne: false,
  })

  const groups: Record<string, Record<string, number>> = {}
  const pipelineMaxStage: Record<string, number> = {}

  for (const [, entry] of Object.entries(metrics)) {
    if (!entry.metric_name.startsWith('latency_p')) continue
    const key = `${entry.pipeline_id}|||${entry.stage_index}`
    if (!groups[key]) groups[key] = {}
    groups[key][entry.metric_name] = entry.mean
    if (entry.stage_index >= 0) {
      pipelineMaxStage[entry.pipeline_id] = Math.max(
        pipelineMaxStage[entry.pipeline_id] ?? 0,
        entry.stage_index
      )
    }
  }

  const groupKeys = Object.keys(groups).sort()
  if (groupKeys.length === 0) return <p className="text-sm text-gray-400">No latency data.</p>

  const isMultiStage = (pipelineId: string) => (pipelineMaxStage[pipelineId] ?? 0) > 0

  const perStageData = groupKeys
    .filter((k) => parseInt(k.split('|||')[1], 10) >= 0)
    .map((rawKey) => {
      const [pipelineId, stageStr] = rawKey.split('|||')
      const stageIndex = parseInt(stageStr, 10)
      return {
        pipelineId,
        label: barLabel(pipelineId, stageIndex, isMultiStage(pipelineId)),
        p50: groups[rawKey]['latency_p50'] ?? 0,
        p95: groups[rawKey]['latency_p95'] ?? 0,
        p99: groups[rawKey]['latency_p99'] ?? 0,
      }
    })

  const totalRows = groupKeys
    .filter((k) => parseInt(k.split('|||')[1], 10) === -1)
    .map((rawKey) => {
      const [pipelineId] = rawKey.split('|||')
      return {
        pipelineId,
        label: `${pipelineAbbrev(pipelineId)} · E2E Total`,
        p50: groups[rawKey]['latency_p50'] ?? 0,
        p95: groups[rawKey]['latency_p95'] ?? 0,
        p99: groups[rawKey]['latency_p99'] ?? 0,
        isTotal: true,
      }
    })

  const chartData = [...perStageData, ...totalRows]

  const pipelineColorMap = useMemo(
    () => buildPipelineColorMap(collectPipelineIds(metrics)),
    [metrics],
  )

  const latencyMax = useMemo(
    () => Math.max(...chartData.map((r) => Math.max(r.p50, r.p95, r.p99)), 1),
    [chartData],
  )

  const yMax = isZoomed ? yDomain[1] * latencyMax : undefined
  const yMin = isZoomed ? yDomain[0] * latencyMax : 0

  const note = (
    <p className="text-xs text-gray-500 mb-2">
      P50 = median · P95 = 95th percentile · P99 = tail latency
      <MetricTooltip text={`${METRIC_GLOSSARY.latency_p50}\n\n${METRIC_GLOSSARY.latency_p95}\n\n${METRIC_GLOSSARY.latency_p99}`} />
      {totalRows.length > 0 && (
        <span className="ml-2 text-gray-400">· &quot;E2E Total&quot; = end-to-end percentiles on per-query total latency</span>
      )}
    </p>
  )

  const renderChart = (height: number) => (
    <ChartFrame height={height}>
      <BarChart data={chartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="label" tick={{ fontSize: 11 }} />
        <YAxis tickFormatter={(v) => `${fmtLatencyMs(v)}ms`} tick={{ fontSize: 11 }} domain={[yMin, yMax ?? 'auto']} />
        <Tooltip formatter={(v: number) => `${fmtLatencyMs(v)} ms`} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="p50" name="P50 (median)" radius={[3, 3, 0, 0]}>
          {chartData.map((row, i) => (
            <Cell key={`p50-${i}`} fill={getPipelineColor(row.pipelineId, pipelineColorMap)} />
          ))}
        </Bar>
        <Bar dataKey="p95" name="P95 (tail)" radius={[3, 3, 0, 0]}>
          {chartData.map((row, i) => (
            <Cell key={`p95-${i}`} fill={withAlpha(getPipelineColor(row.pipelineId, pipelineColorMap), 0.72)} />
          ))}
        </Bar>
        <Bar dataKey="p99" name="P99 (worst-case)" radius={[3, 3, 0, 0]}>
          {chartData.map((row, i) => (
            <Cell key={`p99-${i}`} fill={withAlpha(getPipelineColor(row.pipelineId, pipelineColorMap), 0.48)} />
          ))}
        </Bar>
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
