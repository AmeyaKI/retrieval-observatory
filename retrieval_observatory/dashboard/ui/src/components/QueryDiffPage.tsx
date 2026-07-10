import { useEffect, useMemo, useState } from 'react'
import { fetchRunTraces, RetrievalTraceV2 } from '../api'
import { diffStep, spanOutputs, buildReplaySteps, stepOutputs, CandidateDiffEntry } from '../utils/traceSteps'
import NoData from './NoData'
import SectionHeading from './SectionHeading'

const STATUS_STYLE: Record<string, string> = {
  appeared: 'text-emerald-700 dark:text-emerald-400',
  disappeared: 'text-red-600 dark:text-red-400 line-through',
  rank_changed: 'text-amber-700 dark:text-amber-400',
  unchanged: 'text-ink-faint',
}

// Query Diff View (Item C.2): compares this query's result across two runs, pipeline by
// pipeline. Final-result set diff is the headline; the per-stage divergence walk (using
// spans already fetched, no extra API calls) finds the first operator where the two runs
// actually part ways, since that's usually the real story behind a regression.
export default function QueryDiffPage({
  dbId,
  runId,
  againstRunId,
  queryId,
}: {
  dbId: string
  runId: string
  againstRunId: string
  queryId: string
}) {
  const [tracesA, setTracesA] = useState<RetrievalTraceV2[] | null>(null)
  const [tracesB, setTracesB] = useState<RetrievalTraceV2[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setTracesA(null)
    setTracesB(null)
    setError(null)
    Promise.all([fetchRunTraces(dbId, runId), fetchRunTraces(dbId, againstRunId)])
      .then(([a, b]) => {
        setTracesA(a)
        setTracesB(b)
      })
      .catch((e) => setError(e.message))
  }, [dbId, runId, againstRunId])

  const pairs = useMemo(() => {
    if (!tracesA || !tracesB) return []
    const byPipelineA = new Map(tracesA.filter((t) => t.query_id === queryId).map((t) => [t.pipeline_id, t]))
    const byPipelineB = new Map(tracesB.filter((t) => t.query_id === queryId).map((t) => [t.pipeline_id, t]))
    const common = Array.from(byPipelineA.keys()).filter((p) => byPipelineB.has(p))
    return common.map((pipelineId) => ({
      pipelineId,
      traceA: byPipelineA.get(pipelineId)!,
      traceB: byPipelineB.get(pipelineId)!,
    }))
  }, [tracesA, tracesB, queryId])

  if (error) return <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
  if (!tracesA || !tracesB) {
    return (
      <div className="flex items-center gap-2 text-ink-faint text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 dark:border-slate-600 border-t-indigo-600" />
        Loading diff...
      </div>
    )
  }
  if (pairs.length === 0) {
    return <NoData label="No pipeline ran this query in both runs (or neither run has V2 trace data)." />
  }

  return (
    <div className="space-y-6">
      <p className="text-xs text-ink-muted">
        Query <span className="font-mono">{queryId}</span> — comparing run <span className="font-mono">{runId}</span> against{' '}
        <span className="font-mono">{againstRunId}</span>.
      </p>
      {pairs.map((pair) => (
        <PipelineDiff key={pair.pipelineId} {...pair} />
      ))}
    </div>
  )
}

function PipelineDiff({ pipelineId, traceA, traceB }: { pipelineId: string; traceA: RetrievalTraceV2; traceB: RetrievalTraceV2 }) {
  const stepsA = buildReplaySteps(traceA.spans)
  const stepsB = buildReplaySteps(traceB.spans)
  const finalA = stepsA.length ? stepOutputs(stepsA[stepsA.length - 1]) : new Map<string, number>()
  const finalB = stepsB.length ? stepOutputs(stepsB[stepsB.length - 1]) : new Map<string, number>()
  const finalDiff = diffStep(finalB, finalA) // B = baseline (against), A = current

  const opIdsA = traceA.spans.map((s) => s.op_id)
  const opIdsB = traceB.spans.map((s) => s.op_id)
  const structureMatches = opIdsA.length === opIdsB.length && opIdsA.every((id, i) => id === opIdsB[i])

  const byOpB = new Map(traceB.spans.map((s) => [s.op_id, s]))
  let firstDivergentOp: { opId: string; diff: CandidateDiffEntry[] } | null = null
  if (structureMatches) {
    for (const spanA of traceA.spans) {
      const spanB = byOpB.get(spanA.op_id)
      if (!spanB) continue
      const d = diffStep(spanOutputs(spanB), spanOutputs(spanA))
      if (d.some((e) => e.status !== 'unchanged')) {
        firstDivergentOp = { opId: spanA.op_id, diff: d }
        break
      }
    }
  }

  return (
    <div className="border border-gray-200 dark:border-slate-700 rounded-lg p-3">
      <div className="font-mono text-sm font-semibold mb-2">{pipelineId}</div>

      {!structureMatches && (
        <div className="text-xs text-amber-700 bg-amber-50 dark:bg-amber-950/30 rounded px-2 py-1.5 mb-3">
          Pipeline structure changed between these runs (operator sequence differs) — per-stage divergence walk skipped to avoid a misleading diff. Compare via the Architecture page's topology diff instead.
        </div>
      )}

      {structureMatches && (
        <div className="mb-3">
          <SectionHeading title="First divergent stage" />
          {firstDivergentOp ? (
            <div>
              <div className="text-xs font-mono text-ink mb-1">{firstDivergentOp.opId}</div>
              <CandidateDiffTable diff={firstDivergentOp.diff} />
            </div>
          ) : (
            <NoData label="No operator's output differs between these two runs for this query." />
          )}
        </div>
      )}

      <div>
        <SectionHeading title="Final result diff" />
        <CandidateDiffTable diff={finalDiff} />
      </div>
    </div>
  )
}

function CandidateDiffTable({ diff }: { diff: CandidateDiffEntry[] }) {
  if (diff.length === 0) return <div className="text-xs text-ink-faint">No candidates.</div>
  return (
    <table className="w-full text-[11px]">
      <thead>
        <tr className="text-ink-faint text-left">
          <th className="font-normal pr-2">Doc ID</th>
          <th className="font-normal pr-2">Status</th>
          <th className="font-normal pr-2">Rank (current)</th>
          <th className="font-normal">Rank (baseline)</th>
        </tr>
      </thead>
      <tbody>
        {diff.slice(0, 15).map((d) => (
          <tr key={d.doc_id} className={STATUS_STYLE[d.status]}>
            <td className="pr-2 font-mono truncate max-w-[14rem]">{d.doc_id}</td>
            <td className="pr-2">{d.status.replace('_', ' ')}</td>
            <td className="pr-2 font-mono">{d.rank ?? '—'}</td>
            <td className="font-mono">{d.prevRank ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
