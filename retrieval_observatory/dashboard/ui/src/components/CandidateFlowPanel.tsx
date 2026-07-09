import { useEffect, useState } from 'react'

import { CandidateFlow, CandidateFlowPipeline, fetchCandidateFlow } from '../api'

/**
 * Candidate Flow Visualization (Pillar 2): one document's full journey through every
 * pipeline that ran a query. Makes the vision's five questions visually obvious — which
 * document disappeared, where, why, which reranker promoted it, which arm found it.
 */
export default function CandidateFlowPanel({
  dbId,
  runId,
  queryId,
  docId,
}: {
  dbId: string
  runId: string
  queryId: string
  docId: string
}) {
  const [flow, setFlow] = useState<CandidateFlow | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setFlow(null)
    setError(null)
    fetchCandidateFlow(dbId, runId, queryId, docId)
      .then(setFlow)
      .catch((e) => setError(e.message))
  }, [dbId, runId, queryId, docId])

  if (error) return <div className="text-sm text-red-600 dark:text-red-400">{error}</div>
  if (!flow) return <div className="text-sm text-gray-400">Loading candidate flow…</div>

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold">
        Document <span className="font-mono">{flow.doc_id}</span> — journey through {flow.pipelines.length} pipeline
        {flow.pipelines.length === 1 ? '' : 's'}
      </h3>
      {flow.pipelines.map((p) => (
        <PipelineJourney key={p.trace_id} pipeline={p} />
      ))}
    </div>
  )
}

function PipelineJourney({ pipeline }: { pipeline: CandidateFlowPipeline }) {
  const { history, drop_replay_assumptions } = pipeline
  return (
    <div className="border border-gray-200 dark:border-slate-700 rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="font-mono text-sm">{pipeline.pipeline_id}</span>
        {history.survived ? (
          <span className="px-2 py-0.5 rounded text-xs bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
            survived · final rank {history.final_rank}
          </span>
        ) : (
          <span className="px-2 py-0.5 rounded text-xs bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300">
            dropped at {history.dropped_at} · {history.dropped_reason}
          </span>
        )}
      </div>
      <ol className="space-y-1">
        {history.events.map((e, i) => (
          <li key={i} className="flex items-start gap-2 text-xs">
            <span
              className={`mt-0.5 w-2 h-2 rounded-full shrink-0 ${
                e.event === 'introduced'
                  ? 'bg-sky-500'
                  : e.event === 'dropped'
                    ? 'bg-red-500'
                    : 'bg-slate-400'
              }`}
            />
            <span className="font-mono text-gray-500 dark:text-slate-400">{e.op_name}</span>
            <span className="font-medium">{e.event}</span>
            {e.event === 'passed' && e.score_delta !== null && (
              <span className="text-gray-500 dark:text-slate-400">
                Δscore {e.score_delta >= 0 ? '+' : ''}
                {e.score_delta.toFixed(3)}
              </span>
            )}
            {e.event === 'dropped' && (
              <span className="text-red-600 dark:text-red-400">
                {e.drop_reason}
                {e.drop_reason_inferred ? ' (inferred)' : ''}
              </span>
            )}
            {e.note && <span className="text-gray-400 dark:text-slate-500">— {e.note}</span>}
          </li>
        ))}
      </ol>
      {drop_replay_assumptions && (
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer text-gray-500 dark:text-slate-400">
            Replay verification — how this drop would be counterfactually replayed
          </summary>
          <div className="mt-1 pl-3">
            <div>
              strategy: <span className="font-mono">{drop_replay_assumptions.strategy}</span>
              {drop_replay_assumptions.rrf_recomputed && ` · RRF recomputed (k=${drop_replay_assumptions.rrf_k})`}
            </div>
            <ul className="list-disc pl-4 text-gray-500 dark:text-slate-400">
              {drop_replay_assumptions.caveats.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
        </details>
      )}
    </div>
  )
}
