import { useEffect, useState } from 'react'
import { fetchTraceDetail, TraceDetail as TraceDetailT } from '../../api'
import { difficultyChipClass } from '../../utils/difficulty'
import SuspectedFailureChip from './SuspectedFailureChip'

// Retrieval topology: show candidate flow across stages (entered / survived / dropped),
// computed client-side from the stored per-stage candidate sets.
function lineage(stages: TraceDetailT['stages']) {
  return stages.map((s, i) => {
    const ids = new Set(s.documents.map((d) => d.id))
    if (i === 0) {
      return { stage: s.stage_id, entered: s.documents.length, survived: 0, dropped: 0, count: s.documents.length }
    }
    const prev = new Set(stages[i - 1].documents.map((d) => d.id))
    let survived = 0
    let entered = 0
    for (const id of ids) (prev.has(id) ? survived++ : entered++)
    let dropped = 0
    for (const id of prev) if (!ids.has(id)) dropped++
    return { stage: s.stage_id, entered, survived, dropped, count: s.documents.length }
  })
}

export default function TraceDetail({ traceId, onClose }: { traceId: string; onClose: () => void }) {
  const [trace, setTrace] = useState<TraceDetailT | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchTraceDetail(traceId).then(setTrace).catch((e) => setError(e.message))
  }, [traceId])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white dark:bg-slate-900 rounded-xl shadow-xl max-w-3xl w-full max-h-[85vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 bg-white dark:bg-slate-900 border-b border-gray-200 dark:border-slate-700 px-5 py-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-800 dark:text-slate-100">Trace detail</h2>
          <button type="button" onClick={onClose} className="text-gray-400 dark:text-slate-500 hover:text-gray-700 text-lg leading-none">×</button>
        </div>

        {error && <div className="m-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}
        {!trace && !error && <div className="p-6 text-sm text-gray-400 dark:text-slate-500">Loading…</div>}

        {trace && (
          <div className="p-5 space-y-5">
            <div>
              <p className="text-base text-gray-900 dark:text-slate-100 font-medium">{trace.query_text}</p>
              <div className="flex flex-wrap items-center gap-2 mt-2 text-xs text-gray-500 dark:text-slate-400">
                <span className="font-mono">{trace.pipeline_id}</span>
                <span>·</span>
                <span className={trace.status === 'OK' ? 'text-green-600' : 'text-rose-600 font-medium'}>{trace.status}</span>
                <span>·</span>
                <span>{trace.total_latency_ms.toFixed(0)} ms total</span>
                {trace.predicted_difficulty && (
                  <span className={`px-1.5 py-0.5 rounded border text-[10px] font-medium capitalize ${difficultyChipClass(trace.predicted_difficulty)}`}>
                    {trace.predicted_difficulty}
                  </span>
                )}
              </div>
              {trace.suspected_failures.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {trace.suspected_failures.map((s) => <SuspectedFailureChip key={s} signal={s} />)}
                </div>
              )}
            </div>

            {/* Retrieval topology */}
            <div>
              <p className="text-xs font-semibold text-gray-600 dark:text-slate-300 mb-2">Retrieval topology (candidate flow)</p>
              <div className="flex items-stretch gap-2 overflow-x-auto pb-1">
                {lineage(trace.stages).map((l, i) => (
                  <div key={i} className="flex items-center gap-2 shrink-0">
                    {i > 0 && <span className="text-gray-300 dark:text-slate-600">→</span>}
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800/60 p-3 min-w-[7rem]">
                      <p className="text-xs font-mono text-gray-800 dark:text-slate-100">{l.stage}</p>
                      <p className="text-lg font-bold text-gray-900 dark:text-slate-100 tabular-nums">{l.count}</p>
                      <p className="text-[10px] text-gray-500 dark:text-slate-400">candidates</p>
                      {i > 0 && (
                        <p className="text-[10px] text-gray-400 dark:text-slate-500 mt-1">
                          <span className="text-green-600">{l.survived} kept</span>
                          {' · '}
                          <span className="text-rose-500">{l.dropped} dropped</span>
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Per-stage candidate lists */}
            <div className="space-y-3">
              {trace.stages.map((s) => (
                <div key={s.stage_index}>
                  <p className="text-xs font-semibold text-gray-600 dark:text-slate-300 mb-1">
                    {s.stage_id} <span className="text-gray-400 dark:text-slate-500 font-normal">· {s.latency_ms.toFixed(0)} ms · {s.candidate_count} candidates</span>
                    {s.documents.length > 10 && <span className="text-amber-700 font-normal"> · showing 10 of {s.documents.length}</span>}
                  </p>
                  <div className="border border-gray-200 dark:border-slate-700 rounded overflow-hidden">
                    <table className="w-full text-[11px]">
                      <thead className="bg-gray-50 dark:bg-slate-800/60 text-gray-400 dark:text-slate-500">
                        <tr><th className="text-left px-2 py-1 w-10">#</th><th className="text-left px-2 py-1">Doc</th><th className="text-right px-2 py-1 w-20">Score</th></tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {s.documents.slice(0, 10).map((d) => (
                          <tr key={d.id}>
                            <td className="px-2 py-1 text-gray-400 dark:text-slate-500">{d.rank}</td>
                            <td className="px-2 py-1 font-mono text-gray-700 dark:text-slate-200">{d.id}{d.title ? ` — ${d.title}` : ''}</td>
                            <td className="px-2 py-1 text-right tabular-nums text-gray-600 dark:text-slate-300">{d.score.toFixed(3)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
