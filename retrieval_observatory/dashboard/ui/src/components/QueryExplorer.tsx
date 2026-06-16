import { useEffect, useMemo, useState } from 'react'
import { fetchQueryLabels, QueryLabelRow } from '../api'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'
import { MetricTooltip } from './MetricTooltip'

const AGREEMENT_STYLE: Record<string, string> = {
  match: 'bg-green-100 text-green-800',
  adjacent: 'bg-amber-100 text-amber-800',
  mismatch: 'bg-red-100 text-red-800',
}

const ALL_CLASSES = ['easy', 'medium', 'hard']

function formatProba(proba: Record<string, number> | null | undefined): string {
  if (!proba) return '—'
  return ALL_CLASSES.map((c) => `${c}:${((proba[c] ?? 0) * 100).toFixed(0)}%`).join(' ')
}

export default function QueryExplorer({ dbId, runId }: { dbId: string; runId: string }) {
  const [items, setItems] = useState<QueryLabelRow[]>([])
  const [filter, setFilter] = useState('')
  const [mismatchOnly, setMismatchOnly] = useState(false)

  useEffect(() => {
    fetchQueryLabels(dbId, runId).then((data) => setItems(data.items)).catch(() => setItems([]))
  }, [dbId, runId])

  const filtered = useMemo(() => {
    const needle = filter.toLowerCase()
    return items.filter((item) => {
      if (mismatchOnly && item.agreement !== 'mismatch') return false
      return (
        !needle ||
        item.query_id.toLowerCase().includes(needle) ||
        (item.query_text || '').toLowerCase().includes(needle) ||
        item.actual_bucket.toLowerCase().includes(needle) ||
        (item.actual_class || '').toLowerCase().includes(needle) ||
        (item.predicted_difficulty || '').toLowerCase().includes(needle)
      )
    }).slice(0, 100)
  }, [items, filter, mismatchOnly])

  return (
    <div className="border border-gray-200 rounded bg-white">
      <p className="text-xs text-gray-500 px-3 pt-3 pb-1">
        <strong>Actual</strong> = post-hoc difficulty from mean recall (5 diagnostic buckets → 3-class for agreement).
        <strong className="ml-2">Predicted</strong> = pre-retrieval classifier on query text.
        <MetricTooltip text={`${METRIC_GLOSSARY.actual_difficulty}\n\n${METRIC_GLOSSARY.predicted_difficulty}`} />
      </p>
      <div className="p-3 border-b border-gray-100 flex flex-wrap items-center justify-between gap-3">
        <input
          className="flex-1 min-w-[200px] border border-gray-200 rounded px-2 py-1 text-sm"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter queries, labels, predicted difficulty"
        />
        <label className="flex items-center gap-1.5 text-xs text-gray-600">
          <input type="checkbox" checked={mismatchOnly} onChange={(e) => setMismatchOnly(e.target.checked)} className="rounded border-gray-300" />
          Mismatches only
        </label>
        <span className="text-xs text-gray-400">{filtered.length}/{items.length}</span>
      </div>
      <div className="overflow-x-auto max-h-80">
        <table className="min-w-full text-xs">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              <th className="text-left px-3 py-2">Query</th>
              <th className="text-left px-3 py-2">Text</th>
              <th className="text-left px-3 py-2">Actual (3-class)</th>
              <th className="text-left px-3 py-2">Predicted</th>
              <th className="text-left px-3 py-2">Proba</th>
              <th className="text-left px-3 py-2">Agreement</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.map((item) => (
              <tr key={item.query_id} className="hover:bg-gray-50">
                <td className="px-3 py-2 font-mono">
                  <a href={`#/query/${encodeURIComponent(item.query_id)}`} className="text-indigo-600 hover:underline">
                    {item.query_id}
                  </a>
                </td>
                <td className="px-3 py-2 max-w-xs truncate" title={item.query_text}>
                  {item.query_text || '—'}
                </td>
                <td className="px-3 py-2" title={`Diagnostic bucket: ${item.actual_bucket}`}>
                  {item.actual_class || item.actual_bucket}
                </td>
                <td className="px-3 py-2">{item.predicted_difficulty || '—'}</td>
                <td className="px-3 py-2 font-mono text-[10px] text-gray-600">
                  {formatProba(item.predicted_difficulty_proba)}
                </td>
                <td className="px-3 py-2">
                  {item.agreement ? (
                    <span className={`px-1.5 py-0.5 rounded font-medium ${AGREEMENT_STYLE[item.agreement] ?? ''}`}>
                      {item.agreement}
                    </span>
                  ) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
