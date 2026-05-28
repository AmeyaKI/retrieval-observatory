import { useEffect, useState } from 'react'
import { fetchStageMatrix, MetricEntry } from '../api'
import { formatMetricKey } from '../utils/formatMetricKey'
import { fmtQuality, fmtLatencyMs, fmtCost } from '../utils/format'

type Cell = MetricEntry & { metric: string; estimated_cost_per_1k: number }

interface Props {
  runId: string
  /** Latency budget in ms — highlights latency_p50 cells green/red */
  latencyBudgetMs?: number
}

function fmtCell(v: number, isLatency: boolean): string {
  return isLatency ? fmtLatencyMs(v) : fmtQuality(v)
}

export default function StageCombinationMatrix({ runId, latencyBudgetMs }: Props) {
  const [cells, setCells] = useState<Cell[]>([])

  useEffect(() => {
    fetchStageMatrix(runId).then((data) => setCells(data.cells)).catch(() => setCells([]))
  }, [runId])

  const rows = cells
    .filter((cell) => ['recall', 'ndcg', 'latency_p50', 'latency_p95'].includes(cell.metric_name))
    .slice(0, 80)

  if (!rows.length) return null

  return (
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
                  [{fmtCell(cell.ci_low, isLatency)}, {fmtCell(cell.ci_high, isLatency)}]
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
  )
}
