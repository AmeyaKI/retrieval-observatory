import { useEffect, useState } from 'react'
import { fetchComparison, ComparisonEntry, RunSelection, selectionKey } from '../api'
import { formatMetricKey } from '../utils/formatMetricKey'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'

interface Props {
  selections: RunSelection[]
}

function fmt(v: number | null | undefined): string {
  if (v == null) return '—'
  return v.toFixed(4)
}

export default function ComparePanel({ selections }: Props) {
  const [comparison, setComparison] = useState<ComparisonEntry[] | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  const runKeys = selections.map((s) => `${s.dbId}/${s.runId}`)

  useEffect(() => {
    setComparison(null)
    setWarnings([])
    setError(null)
    fetchComparison(selections)
      .then((data) => {
        setComparison(data.comparison)
        setWarnings(data.warnings ?? [])
      })
      .catch((e) => setError(e.message))
  }, [selections.map(selectionKey).join(',')])

  if (error) {
    return (
      <div className="p-6">
        <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
      </div>
    )
  }

  if (!comparison) {
    return (
      <div className="p-6 flex items-center gap-2 text-gray-400 text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 border-t-indigo-600" />
        Loading comparison...
      </div>
    )
  }

  return (
    <div className="p-6 max-w-6xl">
      <h1 className="text-xl font-bold text-gray-900 mb-1">Run Comparison</h1>
      <p className="text-sm text-gray-500 mb-4 font-mono">{runKeys.join(' vs ')}</p>

      {warnings.length > 0 && (
        <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded text-sm text-amber-900">
          {warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="bg-gray-100 text-left">
              <th className="px-3 py-2 font-semibold text-gray-700">Metric</th>
              {runKeys.map((key) => (
                <th key={key} className="px-3 py-2 font-semibold text-gray-700 text-right font-mono text-xs">
                  {key}
                </th>
              ))}
              <th className="px-3 py-2 font-semibold text-gray-700 text-right">
                p-value
                <MetricTooltip text={METRIC_GLOSSARY.p_value} alignLeft />
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {comparison.map((row) => {
              const pv = row.p_value as number | undefined
              const significant = pv !== undefined && pv < 0.05
              return (
                <tr key={row.metric} className="hover:bg-gray-50">
                  <td className="px-3 py-2 text-xs text-gray-800">{formatMetricKey(row.metric)}</td>
                  {runKeys.map((key) => {
                    const v = row[key] as { mean: number | null; std: number | null } | undefined
                    return (
                      <td key={key} className="px-3 py-2 text-right tabular-nums text-xs">
                        {v?.mean != null ? (
                          <>
                            <span className="font-medium">{fmt(v.mean)}</span>
                            <span className="text-gray-400 ml-1">±{fmt(v.std)}</span>
                          </>
                        ) : '—'}
                      </td>
                    )
                  })}
                  <td className={`px-3 py-2 text-right tabular-nums ${significant ? 'font-bold text-indigo-700' : 'text-gray-400'}`}>
                    {pv !== undefined ? `${pv.toFixed(3)}${significant ? ' *' : ''}` : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-400 mt-3">* p &lt; 0.05 (paired bootstrap significance test)</p>
    </div>
  )
}
