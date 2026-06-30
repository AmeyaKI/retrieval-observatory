import { useEffect, useState } from 'react'
import { fetchStageMatrix, MetricEntry } from '../api'
import { formatMetricKey } from '../utils/formatMetricKey'
import { fmtQuality, fmtLatencyMs, fmtCost } from '../utils/format'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'

type Cell = MetricEntry & { metric: string; estimated_cost_per_1k: number }

interface Props {
  dbId: string
  runId: string
  /** Latency budget in ms — highlights latency_p50 cells green/red */
  latencyBudgetMs?: number
}

function fmtCell(v: number, isLatency: boolean): string {
  return isLatency ? fmtLatencyMs(v) : fmtQuality(v)
}

export default function StageCombinationMatrix({ dbId, runId, latencyBudgetMs }: Props) {
  const [cells, setCells] = useState<Cell[]>([])
  const [page, setPage] = useState(1)
  const pageSize = 50

  useEffect(() => {
    fetchStageMatrix(dbId, runId).then((data) => setCells(data.cells)).catch(() => setCells([]))
    setPage(1)
  }, [dbId, runId])

  const filteredRows = cells
    .filter((cell) => ['recall', 'ndcg', 'latency_p50', 'latency_p95'].includes(cell.metric_name))
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize))
  const currentPage = Math.min(page, totalPages)
  const pageStart = (currentPage - 1) * pageSize
  const rows = filteredRows.slice(pageStart, pageStart + pageSize)
  const totalFiltered = filteredRows.length

  if (!rows.length) return null

  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">Stage metrics table — per-pipeline, per-stage aggregate signals (not a combination heatmap).</p>
      <div className="overflow-x-auto border border-gray-200 rounded bg-white">
      <table className="min-w-full text-xs">
        <thead className="bg-gray-50">
          <tr>
            <th className="text-left px-3 py-2">Signal</th>
            <th className="text-left px-3 py-2">Pipeline</th>
            <th className="text-right px-3 py-2">Mean</th>
            <th className="text-right px-3 py-2">95% CI</th>
            <th className="text-right px-3 py-2">Cost / 1k</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {rows.map((cell) => {
            const isLatency = cell.metric_name.startsWith('latency')
            const isP50 = cell.metric_name === 'latency_p50'
            const withinBudget = isP50 && latencyBudgetMs != null && cell.mean <= latencyBudgetMs
            const overBudget = isP50 && latencyBudgetMs != null && cell.mean > latencyBudgetMs
            const meanCellClass = withinBudget
              ? 'bg-green-50 text-green-700'
              : overBudget
              ? 'bg-red-50 text-red-600'
              : ''

            return (
              <tr key={cell.metric} className="hover:bg-gray-50">
                <td className="px-3 py-2">{formatMetricKey(cell.metric)}</td>
                <td className="px-3 py-2 font-mono">{cell.pipeline_id}</td>
                <td className={`px-3 py-2 text-right tabular-nums ${meanCellClass}`}>
                  {fmtCell(cell.mean, isLatency)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {cell.ci_low != null && cell.ci_high != null
                    ? `[${fmtCell(cell.ci_low, isLatency)}, ${fmtCell(cell.ci_high, isLatency)}]`
                    : '—'}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {cell.estimated_cost_per_1k ? fmtCost(cell.estimated_cost_per_1k) : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      </div>
      {totalFiltered > pageSize && (
        <div className="mt-2 flex items-center justify-between text-xs text-gray-600">
          <p>
            Showing {pageStart + 1}-{Math.min(pageStart + pageSize, totalFiltered)} of {totalFiltered} rows.
            <MetricTooltip text={METRIC_GLOSSARY.truncation_notice} />
          </p>
          <div className="flex items-center gap-2">
            <button
              className="px-2 py-1 rounded border border-gray-300 disabled:opacity-50"
              disabled={currentPage <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Prev
            </button>
            <span>
              Page {currentPage}/{totalPages}
            </span>
            <button
              className="px-2 py-1 rounded border border-gray-300 disabled:opacity-50"
              disabled={currentPage >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
