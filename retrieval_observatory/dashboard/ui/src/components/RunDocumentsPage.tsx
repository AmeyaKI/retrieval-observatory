import { useEffect, useState } from 'react'
import { fetchQueryLabels, fetchQueryResult, QueryLabelRow, QueryResult } from '../api'

// The final disclosure-spine level (retobs_finer.md Pillar 1): raw per-pipeline,
// per-stage documents for one query, so a user can verify a claim all the way down
// to the actual retrieved document IDs and scores.
export default function RunDocumentsPage({ dbId, runId }: { dbId: string; runId: string }) {
  const [queries, setQueries] = useState<QueryLabelRow[] | null>(null)
  const [queryId, setQueryId] = useState<string>('')
  const [result, setResult] = useState<QueryResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchQueryLabels(dbId, runId)
      .then((r) => {
        setQueries(r.items)
        if (r.items.length > 0) setQueryId(r.items[0].query_id)
      })
      .catch((e) => setError(e.message))
  }, [dbId, runId])

  useEffect(() => {
    if (!queryId) return
    setResult(null)
    fetchQueryResult(dbId, runId, queryId)
      .then(setResult)
      .catch((e) => setError(e.message))
  }, [dbId, runId, queryId])

  if (error) return <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>

  return (
    <div className="space-y-4">
      <p className="text-xs text-ink-muted">
        Raw retrieved documents, per pipeline and per stage, for a single query — the ground truth behind every metric on this run.
      </p>
      <div className="flex items-center gap-2">
        <label className="text-xs text-ink-muted">Query</label>
        <select
          value={queryId}
          onChange={(e) => setQueryId(e.target.value)}
          className="text-xs border border-gray-300 dark:border-slate-600 rounded px-2 py-1 bg-white dark:bg-slate-900 text-ink"
        >
          {(queries ?? []).map((q) => (
            <option key={q.query_id} value={q.query_id}>
              {q.query_id} — {q.query_text.slice(0, 60)}
            </option>
          ))}
        </select>
      </div>

      {!result ? (
        <div className="flex items-center gap-2 text-ink-faint text-sm">
          <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 dark:border-slate-600 border-t-indigo-600" />
          Loading documents...
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {result.results.map((pipeline) => (
            <div key={pipeline.pipeline_id} className="border border-gray-200 dark:border-slate-700 rounded-lg overflow-hidden">
              <div className="px-3 py-2 bg-surface-muted border-b border-gray-200 dark:border-slate-700 flex items-center justify-between">
                <span className="text-xs font-semibold text-ink">{pipeline.pipeline_id}</span>
                <span className="text-xs text-ink-muted">{pipeline.status} · {pipeline.total_latency_ms.toFixed(0)}ms</span>
              </div>
              <div className="divide-y divide-gray-100 dark:divide-slate-800">
                {pipeline.stages.map((stage) => (
                  <div key={stage.stage_id} className="p-3">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-medium text-ink">{stage.stage_id}</span>
                      <span className="text-xs text-ink-faint">
                        {stage.candidate_count ?? stage.documents.length} candidates · {stage.latency_ms.toFixed(1)}ms
                      </span>
                    </div>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-ink-faint text-left">
                          <th className="font-normal pr-2">Rank</th>
                          <th className="font-normal pr-2">Doc ID</th>
                          <th className="font-normal">Score</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stage.documents.slice(0, 10).map((doc) => (
                          <tr key={doc.id} className="text-ink">
                            <td className="pr-2 font-mono">{doc.rank}</td>
                            <td className="pr-2 font-mono truncate max-w-[16rem]">{doc.id}</td>
                            <td className="font-mono">{doc.score.toFixed(4)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
