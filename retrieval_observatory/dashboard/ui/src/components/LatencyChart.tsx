import { useCallback, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend,
} from 'recharts'
import { MetricsMap } from '../api'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'
import { fmtLatencyMs } from '../utils/format'
import { ChartModal } from './ChartModal'
import ChartFrame from './ChartFrame'

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
  const [yZoomFactor, setYZoomFactor] = useState(1.0)
  const isZoomed = yZoomFactor < 0.999

  const handleWheel = useCallback((e: React.WheelEvent<HTMLDivElement>) => {
    if (!e.ctrlKey) return
    e.preventDefault()
    const factor = e.deltaY > 0 ? 1.15 : 0.87
    setYZoomFactor((prev) => Math.max(0.05, Math.min(1.0, prev * factor)))
  }, [])

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
        label: `${pipelineAbbrev(pipelineId)} · E2E Total`,
        p50: groups[rawKey]['latency_p50'] ?? 0,
        p95: groups[rawKey]['latency_p95'] ?? 0,
        p99: groups[rawKey]['latency_p99'] ?? 0,
        isTotal: true,
      }
    })

  const chartData = [...perStageData, ...totalRows]

  const note = (
    <p className="text-xs text-gray-500 mb-2">
      P50 = median · P95 = 95th percentile · P99 = tail latency
      <MetricTooltip text={`${METRIC_GLOSSARY.latency_p50}\n\n${METRIC_GLOSSARY.latency_p95}\n\n${METRIC_GLOSSARY.latency_p99}`} />
      {totalRows.length > 0 && (
        <span className="ml-2 text-gray-400">· "E2E Total" = true end-to-end percentiles computed on per-query total latency</span>
      )}
    </p>
  )

  const dataMax = Math.max(...chartData.map((r) => Math.max(r.p50, r.p95, r.p99)), 1) * 1.1
  const yMax = isZoomed ? dataMax * yZoomFactor : undefined

  const renderChart = (height: number) => (
    <ChartFrame height={height}>
      <BarChart data={chartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="label" tick={{ fontSize: 11 }} />
        <YAxis tickFormatter={(v) => `${fmtLatencyMs(v)}ms`} tick={{ fontSize: 11 }} domain={[0, yMax ?? 'auto']} />
        <Tooltip formatter={(v: number) => `${fmtLatencyMs(v)} ms`} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="p50" fill="#6366f1" name="P50 (median)" radius={[3, 3, 0, 0]} />
        <Bar dataKey="p95" fill="#f59e0b" name="P95 (tail)" radius={[3, 3, 0, 0]} />
        <Bar dataKey="p99" fill="#ef4444" name="P99 (worst-case)" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ChartFrame>
  )

  return (
    <div>
      {note}
      <div className="flex justify-end gap-2 mb-1">
        {isZoomed && (
          <button onClick={() => setYZoomFactor(1.0)} className="text-xs text-indigo-600 hover:text-indigo-800 border border-indigo-200 rounded px-2 py-0.5">
            Reset zoom
          </button>
        )}
        <button
          onClick={() => setExpanded(true)}
          className="text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded px-2 py-0.5"
        >
          Expand ⤢
        </button>
      </div>
      <div onWheel={handleWheel} style={{ touchAction: 'none' }}>
        {renderChart(260)}
      </div>
      {expanded && (
        <ChartModal title="Latency Percentiles" onClose={() => setExpanded(false)}>
          {note}
          <div onWheel={handleWheel} style={{ touchAction: 'none' }}>
            {renderChart(500)}
          </div>
        </ChartModal>
      )}
    </div>
  )
}
