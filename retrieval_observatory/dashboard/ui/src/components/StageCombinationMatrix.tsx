import { useEffect, useState } from 'react'
import { fetchStageMatrix, MetricEntry } from '../api'
import { formatMetricKey } from '../utils/formatMetricKey'

type Cell = MetricEntry & { metric: string; estimated_cost_per_1k: number }

export default function StageCombinationMatrix({ runId }: { runId: string }) {
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
          {rows.map((cell) => (
            <tr key={cell.metric} className="hover:bg-gray-50">
              <td className="px-3 py-2">{formatMetricKey(cell.metric)}</td>
              <td className="px-3 py-2 font-mono">{cell.pipeline_id}</td>
              <td className="px-3 py-2 text-right tabular-nums">{cell.mean.toFixed(4)}</td>
              <td className="px-3 py-2 text-right tabular-nums">[{cell.ci_low.toFixed(4)}, {cell.ci_high.toFixed(4)}]</td>
              <td className="px-3 py-2 text-right tabular-nums">{cell.estimated_cost_per_1k ? `$${cell.estimated_cost_per_1k.toFixed(2)}` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
