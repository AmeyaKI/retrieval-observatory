import { MetricEntry, MetricsMap } from '../api'
import { formatMetricKey } from '../utils/formatMetricKey'

interface Props {
  metrics: MetricsMap
  pValues?: Record<string, number>
  /** Published baselines keyed by "metric@k" e.g. {"ndcg@10": 0.326} */
  baselines?: Record<string, number>
}

function fmt(v: number): string {
  return v.toFixed(4)
}

function ciLabel(entry: MetricEntry): string {
  return `[${fmt(entry.ci_low)}, ${fmt(entry.ci_high)}]`
}

export default function MetricsTable({ metrics, pValues, baselines = {} }: Props) {
  const entries = Object.entries(metrics).sort(([a], [b]) => a.localeCompare(b))
  const hasBaselines = Object.keys(baselines).length > 0

  if (entries.length === 0) {
    return <p className="text-sm text-gray-400">No metrics available.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="bg-gray-100 text-left">
            <th className="px-3 py-2 font-semibold text-gray-700">Metric</th>
            <th className="px-3 py-2 font-semibold text-gray-700 text-right">Mean</th>
            <th className="px-3 py-2 font-semibold text-gray-700 text-right">Std</th>
            <th className="px-3 py-2 font-semibold text-gray-700 text-right">95% CI</th>
            <th className="px-3 py-2 font-semibold text-gray-700 text-right">N</th>
            <th className="px-3 py-2 font-semibold text-gray-700 text-right">Zero%</th>
            {hasBaselines && (
              <th className="px-3 py-2 font-semibold text-gray-500 text-right text-xs">Ref (BM25)</th>
            )}
            {pValues && <th className="px-3 py-2 font-semibold text-gray-700 text-right">p-value</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {entries.map(([key, entry]) => {
            const pv = pValues?.[key]
            const significant = pv !== undefined && pv < 0.05
            const isLatency = entry.metric_name.startsWith('latency')
            // Lookup baseline by "metricname@k" (e.g. "ndcg@10", "recall@10")
            const baselineKey = entry.k > 0 ? `${entry.metric_name}@${entry.k}` : null
            const baselineVal = baselineKey ? baselines[baselineKey] : undefined
            return (
              <tr key={key} className="hover:bg-gray-50">
                <td className="px-3 py-2 text-gray-800">{formatMetricKey(key)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{fmt(entry.mean)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-500">{fmt(entry.std)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-600 text-xs">{ciLabel(entry)}</td>
                <td className="px-3 py-2 text-right text-gray-500">{entry.n}</td>
                <td className="px-3 py-2 text-right text-gray-400 text-xs">
                  {isLatency ? '—' : `${entry.zero_pct}%`}
                </td>
                {hasBaselines && (
                  <td className="px-3 py-2 text-right text-gray-400 text-xs tabular-nums">
                    {baselineVal !== undefined ? fmt(baselineVal) : '—'}
                  </td>
                )}
                {pValues && (
                  <td className={`px-3 py-2 text-right tabular-nums ${significant ? 'font-bold text-indigo-700' : 'text-gray-500'}`}>
                    {pv !== undefined ? `${pv.toFixed(3)}${significant ? ' *' : ''}` : '—'}
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
