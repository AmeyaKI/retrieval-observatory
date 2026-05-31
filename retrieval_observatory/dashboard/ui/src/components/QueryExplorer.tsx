import { useEffect, useMemo, useState } from 'react'
import { fetchQueryLabels, QueryLabelRow } from '../api'

const AGREEMENT_STYLE: Record<string, string> = {
  match: 'bg-green-100 text-green-800',
  adjacent: 'bg-amber-100 text-amber-800',
  mismatch: 'bg-red-100 text-red-800',
}

export default function QueryExplorer({ runId }: { runId: string }) {
  const [items, setItems] = useState<QueryLabelRow[]>([])
  const [filter, setFilter] = useState('')

  useEffect(() => {
    fetchQueryLabels(runId).then((data) => setItems(data.items)).catch(() => setItems([]))
  }, [runId])

  const filtered = useMemo(() => {
    const needle = filter.toLowerCase()
    return items.filter((item) =>
      !needle ||
      item.query_id.toLowerCase().includes(needle) ||
      (item.query_text || '').toLowerCase().includes(needle) ||
      item.actual_bucket.toLowerCase().includes(needle) ||
      (item.predicted_difficulty || '').toLowerCase().includes(needle)
    ).slice(0, 100)
  }, [items, filter])

  return (
    <div className="border border-gray-200 rounded bg-white">
      <div className="p-3 border-b border-gray-100 flex items-center justify-between gap-3">
        <input
          className="w-full max-w-sm border border-gray-200 rounded px-2 py-1 text-sm"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter queries, labels, predicted difficulty"
        />
        <span className="text-xs text-gray-400">{filtered.length}/{items.length}</span>
      </div>
      <div className="overflow-x-auto max-h-80">
        <table className="min-w-full text-xs">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              <th className="text-left px-3 py-2">Query</th>
              <th className="text-left px-3 py-2">Text</th>
              <th className="text-left px-3 py-2">Actual</th>
              <th className="text-left px-3 py-2">Predicted</th>
              <th className="text-left px-3 py-2">Agreement</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.map((item) => (
              <tr key={item.query_id} className="hover:bg-gray-50">
                <td className="px-3 py-2 font-mono">{item.query_id}</td>
                <td className="px-3 py-2 max-w-xs truncate" title={item.query_text}>
                  {item.query_text || '—'}
                </td>
                <td className="px-3 py-2">{item.actual_bucket}</td>
                <td className="px-3 py-2">{item.predicted_difficulty || '—'}</td>
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
