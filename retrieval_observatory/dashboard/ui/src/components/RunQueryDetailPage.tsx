import { useEffect, useMemo, useState } from 'react'
import {
  fetchAdvisorRecommendations,
  fetchOperatorDiff,
  fetchQueryLabels,
  fetchQueryLineage,
  fetchRunTraces,
  OperatorDiff,
  QueryLineage,
  Recommendation,
  RetrievalTraceV2,
} from '../api'
import { OP_ACCENT } from '../utils/opTypeColors'
import { droppedDocIds } from '../utils/traceSteps'
import TraceWaterfall from './TraceWaterfall'
import QueryReplayScrubber from './QueryReplayScrubber'
import NoData from './NoData'
import SectionHeading from './SectionHeading'

// The unified query timeline (RETOBS_FINER_PLAN_PHASE2.md Item C.1): one query's full
// journey across every pipeline that ran it. Origin, regression history, and production
// matches are sourced from the existing fetchQueryLineage endpoint (built for the /query/:id
// cross-run lineage page) rather than new backend endpoints -- it already returns exactly
// this data keyed by query_id, and Item 0 already stabilized that identity.
export default function RunQueryDetailPage({ dbId, runId, queryId }: { dbId: string; runId: string; queryId: string }) {
  const [traces, setTraces] = useState<RetrievalTraceV2[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<{ traceId: string; opId: string } | null>(null)
  const [diff, setDiff] = useState<OperatorDiff | null>(null)
  const [diffError, setDiffError] = useState<string | null>(null)
  const [replayFor, setReplayFor] = useState<string | null>(null)
  const [lineage, setLineage] = useState<QueryLineage | null>(null)
  const [recommendations, setRecommendations] = useState<Recommendation[] | null>(null)
  const [diagnosticLabels, setDiagnosticLabels] = useState<Set<string>>(new Set())

  useEffect(() => {
    setTraces(null)
    setError(null)
    setSelected(null)
    setReplayFor(null)
    fetchRunTraces(dbId, runId)
      .then(setTraces)
      .catch((e) => setError(e.message))
  }, [dbId, runId])

  useEffect(() => {
    setLineage(null)
    fetchQueryLineage(queryId)
      .then(setLineage)
      .catch(() => setLineage(null))
    fetchAdvisorRecommendations(runId)
      .then((r) => setRecommendations(r.recommendations))
      .catch(() => setRecommendations([]))
    fetchQueryLabels(dbId, runId)
      .then((r) => {
        const row = r.items.find((item) => item.query_id === queryId)
        if (!row) return
        const labels = new Set<string>()
        if (row.actual_bucket) labels.add(row.actual_bucket)
        if (row.actual_class) labels.add(row.actual_class)
        if (row.predicted_difficulty) labels.add(row.predicted_difficulty)
        for (const risk of row.predicted_risks ?? []) labels.add(risk)
        setDiagnosticLabels(labels)
      })
      .catch(() => setDiagnosticLabels(new Set()))
  }, [dbId, queryId, runId])

  useEffect(() => {
    if (!selected) {
      setDiff(null)
      return
    }
    setDiff(null)
    setDiffError(null)
    fetchOperatorDiff(dbId, runId, selected.traceId, selected.opId)
      .then(setDiff)
      .catch((e) => setDiffError(e.message))
  }, [dbId, runId, selected])

  const queryTraces = useMemo(
    () => (traces ?? []).filter((t) => t.query_id === queryId),
    [traces, queryId],
  )

  const relevantRecommendations = useMemo(() => {
    if (!recommendations) return []
    return recommendations.filter(
      (r) => !r.affected_query_categories || r.affected_query_categories.length === 0 || r.affected_query_categories.some((c) => diagnosticLabels.has(c)),
    )
  }, [recommendations, diagnosticLabels])

  if (error) return <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
  if (!traces) {
    return (
      <div className="flex items-center gap-2 text-ink-faint text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 dark:border-slate-600 border-t-indigo-600" />
        Loading query timeline...
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <OriginSection lineage={lineage} />

      {queryTraces.length === 0 ? (
        <NoData label="No operator-level trace data for this query (this run may predate V2 tracing, or the query is not in this run)." />
      ) : (
        <div>
          <SectionHeading title="Benchmark results & stage transitions" />
          <p className="text-xs text-ink-muted mb-3">
            {queryTraces.length} pipeline trace{queryTraces.length === 1 ? '' : 's'}. Click an operator bar for its input/output diff; use Replay to step through candidate-set changes one operator at a time.
          </p>
          <div className="space-y-4">
            {queryTraces.map((trace) => {
              const dropped = droppedDocIds(trace.spans)
              return (
                <div key={trace.trace_id} className="border border-gray-200 dark:border-slate-700 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-sm font-semibold">{trace.pipeline_id}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-ink-muted">{trace.status} · {trace.total_latency_ms.toFixed(1)}ms</span>
                      <button
                        type="button"
                        onClick={() => setReplayFor(replayFor === trace.trace_id ? null : trace.trace_id)}
                        className="text-[10px] px-1.5 py-0.5 rounded border border-gray-200 dark:border-slate-700 text-ink-muted hover:text-indigo-600 hover:border-indigo-300"
                      >
                        {replayFor === trace.trace_id ? 'Hide replay' : 'Replay ▶'}
                      </button>
                    </div>
                  </div>
                  <TraceWaterfall
                    spans={trace.spans}
                    onSelectOp={(opId) => setSelected({ traceId: trace.trace_id, opId })}
                  />
                  {replayFor === trace.trace_id && (
                    <div className="mt-3 border-t border-gray-100 dark:border-slate-800 pt-3">
                      <SectionHeading title="Step-through replay" />
                      <QueryReplayScrubber spans={trace.spans} />
                    </div>
                  )}
                  {selected?.traceId === trace.trace_id && (
                    <div className="mt-3 border-t border-gray-100 dark:border-slate-800 pt-3">
                      <SectionHeading title={`Operator diff — ${selected.opId}`} />
                      {diffError && <div className="text-xs text-red-600">{diffError}</div>}
                      {!diffError && !diff && <div className="text-xs text-ink-faint">Loading diff...</div>}
                      {diff && <OperatorDiffView diff={diff} />}
                    </div>
                  )}
                  {dropped.length > 0 && (
                    <div className="mt-3 border-t border-gray-100 dark:border-slate-800 pt-2">
                      <div className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide mb-1">
                        Dropped candidates ({dropped.length})
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {dropped.slice(0, 12).map((docId) => (
                          <a
                            key={docId}
                            href={`#/benchmarks/run/${encodeURIComponent(runId)}/queries/${encodeURIComponent(queryId)}/candidates/${encodeURIComponent(docId)}`}
                            className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300 hover:underline"
                          >
                            {docId}
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      <RegressionHistorySection lineage={lineage} runId={runId} queryId={queryId} />
      <ProductionMatchesSection lineage={lineage} />
      <RecommendationsSection recommendations={relevantRecommendations} />
    </div>
  )
}

function OriginSection({ lineage }: { lineage: QueryLineage | null }) {
  const forge = lineage?.origin?.forge
  return (
    <div>
      <SectionHeading title="Origin" />
      {!lineage ? (
        <div className="text-xs text-ink-faint">Loading…</div>
      ) : forge ? (
        <div className="text-xs text-ink-muted">
          Forge scenario <span className="font-mono">{forge.scenario_id}</span> ({forge.scenario_type}, {forge.difficulty_label}) —{' '}
          {forge.positive_doc_ids?.length ? `${forge.positive_doc_ids.length} positive doc(s)` : 'no positive docs recorded'}.{' '}
          {forge.evidence_summary && <span>{forge.evidence_summary}</span>}{' '}
          <a href={`#/forge/${encodeURIComponent(forge.dataset_id)}`} className="text-indigo-600 hover:underline">
            View Forge dataset →
          </a>
        </div>
      ) : (
        <NoData label={`No Forge origin recorded${lineage.origin?.dataset_name ? ` — from dataset "${lineage.origin.dataset_name}"` : ''}.`} />
      )}
    </div>
  )
}

function RegressionHistorySection({ lineage, runId, queryId }: { lineage: QueryLineage | null; runId: string; queryId: string }) {
  const evaluations = (lineage?.evaluations ?? []).filter((e) => e.run_id !== runId)
  return (
    <div>
      <SectionHeading title="Regression history" />
      {!lineage ? (
        <div className="text-xs text-ink-faint">Loading…</div>
      ) : evaluations.length === 0 ? (
        <NoData label="This query hasn't been evaluated in any other run." />
      ) : (
        <div className="space-y-1">
          {evaluations.map((ev) => (
            <div key={ev.run_id} className="flex items-center justify-between text-xs border border-gray-100 dark:border-slate-800 rounded px-2 py-1.5">
              <span>
                <span className="font-medium">{ev.experiment_name}</span>{' '}
                <span className="text-ink-faint font-mono">{ev.run_id}</span>{' '}
                <span className="text-ink-faint">· {ev.started_at}</span>
              </span>
              <a
                href={`#/benchmarks/run/${encodeURIComponent(runId)}/queries/${encodeURIComponent(queryId)}/diff?against=${encodeURIComponent(ev.run_id)}`}
                className="text-indigo-600 hover:underline"
              >
                diff against this run →
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ProductionMatchesSection({ lineage }: { lineage: QueryLineage | null }) {
  const matches = lineage?.production_matches
  return (
    <div>
      <SectionHeading title="Production traces" />
      {!lineage ? (
        <div className="text-xs text-ink-faint">Loading…</div>
      ) : !matches || matches.traces.length === 0 ? (
        <NoData label={matches?.note || 'No matching production traces found.'} />
      ) : (
        <div className="space-y-1">
          <p className="text-xs text-ink-muted">{matches.note} ({matches.match_type})</p>
          {matches.traces.map((t) => (
            <div key={t.trace_id} className="text-xs border border-gray-100 dark:border-slate-800 rounded px-2 py-1.5 flex items-center justify-between">
              <span className="font-mono">{t.trace_id}</span>
              <span className="text-ink-faint">{t.service} · {t.predicted_difficulty ?? '—'}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function RecommendationsSection({ recommendations }: { recommendations: Recommendation[] }) {
  return (
    <div>
      <SectionHeading title="Recommendations" />
      {recommendations.length === 0 ? (
        <NoData label="No recommendations affect this query's diagnostic category." />
      ) : (
        <ul className="text-xs space-y-1">
          {recommendations.slice(0, 5).map((r, i) => (
            <li key={i} className="border border-gray-100 dark:border-slate-800 rounded px-2 py-1.5">
              <div className="font-medium">{r.action}</div>
              <div className="text-ink-faint">{r.rationale}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function OperatorDiffView({ diff }: { diff: OperatorDiff }) {
  const accent = OP_ACCENT[diff.op_type] ?? OP_ACCENT.TRANSFORM
  const columns: Array<{ label: string; docs: OperatorDiff['inputs'] }> = [
    { label: 'Input', docs: diff.inputs },
    { label: 'Output', docs: diff.outputs },
    { label: 'Without this operator (counterfactual)', docs: diff.without_operator },
  ]
  return (
    <div>
      <div className="flex items-center gap-2 mb-2 text-xs">
        <span
          className="px-1.5 py-0.5 rounded border font-medium"
          style={{ background: accent.fill, borderColor: accent.stroke, color: accent.text }}
        >
          {diff.op_type}
        </span>
        <span className="text-ink-muted">replay: {diff.replay_policy}</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {columns.map((col) => (
          <div key={col.label} className="border border-gray-100 dark:border-slate-800 rounded p-2">
            <div className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide mb-1">{col.label}</div>
            <table className="w-full text-[11px]">
              <tbody>
                {col.docs.slice(0, 10).map((doc) => (
                  <tr key={doc.doc_id}>
                    <td className="pr-1 font-mono text-ink-faint">{doc.rank}</td>
                    <td className="pr-1 font-mono truncate max-w-[8rem]">{doc.doc_id}</td>
                    <td className="text-right font-mono">{doc.score.toFixed(3)}</td>
                  </tr>
                ))}
                {col.docs.length === 0 && (
                  <tr><td className="text-ink-faint">—</td></tr>
                )}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  )
}
