import { useEffect, useState } from 'react'
import { fetchQueryWinners, QueryWinnerRow } from '../api'
import NoData from './NoData'
import SectionHeading from './SectionHeading'

interface Props {
  dbId: string
  runId: string
}

export default function QueryWinnerTable({ dbId, runId }: Props) {
  const [items, setItems] = useState<QueryWinnerRow[]>([])
  useEffect(() => {
    fetchQueryWinners(dbId, runId)
      .then((res) => setItems(res.items))
      .catch(() => setItems([]))
  }, [dbId, runId])

  if (items.length === 0) return <NoData label="No per-query winner data available." />

  return (
    <div>
      <SectionHeading title="Per-query winners" />
      <div className="overflow-x-auto border border-gray-200 dark:border-slate-700 rounded bg-white dark:bg-slate-900">
        <table className="min-w-full text-xs">
          <thead className="bg-gray-50 dark:bg-slate-800/60">
            <tr>
              <th className="text-left px-3 py-2">Query</th>
              <th className="text-left px-3 py-2">Winner</th>
              <th className="text-right px-3 py-2">Score</th>
              <th className="text-left px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {items.map((row) => (
              <tr key={row.query_id}>
                <td className="px-3 py-2 font-mono">{row.query_id}</td>
                <td className="px-3 py-2">{row.winner_pipeline_id ?? '—'}</td>
                <td className="px-3 py-2 text-right">{row.score != null ? row.score.toFixed(3) : '—'}</td>
                <td className="px-3 py-2">{row.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
