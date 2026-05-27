import { useEffect, useMemo, useState } from 'react'
import { fetchDiagnostics, QueryDiagnostic } from '../api'

export default function QueryExplorer({ runId }: { runId: string }) {
  const [items, setItems] = useState<QueryDiagnostic[]>([])
  const [filter, setFilter] = useState('')

  useEffect(() => {
    fetchDiagnostics(runId).then((data) => setItems(data.items)).catch(() => setItems([]))
  }, [runId])

  const filtered = useMemo(() => {
    const needle = filter.toLowerCase()
    return items.filter((item) =>
      !needle ||
      item.query_id.toLowerCase().includes(needle) ||
      item.pipeline_id.toLowerCase().includes(needle) ||
      item.failure_labels.join(' ').toLowerCase().includes(needle) ||
      item.difficulty_bucket.toLowerCase().includes(needle)
    ).slice(0, 100)
  }, [items, filter])

  return (
    <div className="border border-gray-200 rounded bg-white">
      <div className="p-3 border-b border-gray-100 flex items-center justify-between gap-3">
        <input
          className="w-full max-w-sm border border-gray-200 rounded px-2 py-1 text-sm"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter queries, pipelines, labels"
        />
        <span className="text-xs text-gray-400">{filtered.length}/{items.length}</span>
      </div>
      <div className="overflow-x-auto max-h-80">
        <table className="min-w-full text-xs">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              <th className="text-left px-3 py-2">Query</th>
              <th className="text-left px-3 py-2">Pipeline</th>
              <th className="text-left px-3 py-2">Difficulty</th>
              <th className="text-left px-3 py-2">Labels</th>
              <th className="text-left px-3 py-2">Missing Relevant</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.map((item) => (
              <tr key={`${item.query_id}-${item.pipeline_id}`} className="hover:bg-gray-50">
                <td className="px-3 py-2 font-mono">{item.query_id}</td>
                <td className="px-3 py-2 font-mono">{item.pipeline_id}</td>
                <td className="px-3 py-2">{item.difficulty_bucket}</td>
                <td className="px-3 py-2">{item.failure_labels.join(', ') || '—'}</td>
                <td className="px-3 py-2 font-mono">{item.missing_relevant_ids.slice(0, 4).join(', ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
