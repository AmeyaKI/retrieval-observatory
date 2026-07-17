import { useEffect, useMemo, useState } from 'react'
import {
  fetchOperatorDiff,
  fetchQueryEvidence,
  OperatorDiff,
  QueryEvidence,
  QueryLineage,
  Recommendation,
} from '../api'
import { OP_ACCENT } from '../utils/opTypeColors'
import { droppedDocIds } from '../utils/traceSteps'
import { relevantDocumentOutcomes } from '../utils/queryDebugger'
import TraceWaterfall from './TraceWaterfall'
import QueryReplayScrubber from './QueryReplayScrubber'
import NoData from './NoData'
import SectionHeading from './SectionHeading'
import StatusPanel from './StatusPanel'

// The unified query timeline (RETOBS_FINER_PLAN_PHASE2.md Item C.1): one query's full
// journey across every pipeline that ran it. Origin, regression history, and production
// matches are sourced from the existing fetchQueryLineage endpoint (built for the /query/:id
// cross-run lineage page) rather than new backend endpoints -- it already returns exactly
// this data keyed by query_id, and Item 0 already stabilized that identity.
export default function RunQueryDetailPage({ dbId, runId, queryId }: { dbId: string; runId: string; queryId: string }) {
  const [evidence, setEvidence] = useState<QueryEvidence | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<{ traceId: string; opId: string } | null>(null)
  const [diff, setDiff] = useState<OperatorDiff | null>(null)
  const [diffError, setDiffError] = useState<string | null>(null)
  const [replayFor, setReplayFor] = useState<string | null>(null)

  useEffect(() => {
    setEvidence(null)
    setError(null)
    setSelected(null)
    setReplayFor(null)
    fetchQueryEvidence(dbId, runId, queryId)
      .then(setEvidence)
      .catch((e) => setError(e.message))
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

  const queryTraces = evidence?.traces ?? []
  const relevantOutcomes = useMemo(
    () => relevantDocumentOutcomes(queryTraces, evidence?.ground_truth.relevant_doc_ids ?? []),
    [evidence?.ground_truth.relevant_doc_ids, queryTraces],
  )
  const lineage = useMemo(() => evidence ? ({
    query_id: queryId,
    origin: evidence.origin ?? {},
    evaluations: evidence.regression_history,
    production_matches: evidence.production_matches ?? { traces: [], note: '', match_type: 'none', match_failure_labels: [] },
  } as QueryLineage) : null, [evidence, queryId])

  if (error) return <StatusPanel kind="error" title="Query evidence could not be loaded" message={error} />
  if (!evidence) {
    return <StatusPanel kind="loading" message="Loading query evidence and candidate transitions…" />
  }

  return (
    <div className="space-y-6">
      <section aria-labelledby="query-evidence-heading" className="rounded-xl border border-slate-300 dark:border-slate-700 bg-surface p-4">
        <h2 id="query-evidence-heading" className="text-base font-semibold text-ink">Query evidence</h2>
        <p className="mt-2 text-sm text-ink">{evidence.query.text ?? 'Query text unavailable'}</p>
        <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-3">
          <div><dt className="text-ink-faint">Query ID</dt><dd className="font-mono text-ink">{queryId}</dd></div>
          <div><dt className="text-ink-faint">Dataset</dt><dd className="text-ink">{evidence.query.dataset_name ?? 'unavailable'}</dd></div>
          <div><dt className="text-ink-faint">Ground truth</dt><dd className="text-ink">{evidence.ground_truth.evidence_class} · {evidence.ground_truth.relevant_doc_ids.length} relevant document(s)</dd></div>
        </dl>
        {evidence.ground_truth.relevant_doc_ids.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1" aria-label="Relevant documents">
            {evidence.ground_truth.relevant_doc_ids.map((docId) => <span key={docId} className="rounded border px-1.5 py-0.5 font-mono text-[11px]">{docId} (grade {evidence.ground_truth.grades[docId]})</span>)}
          </div>
        )}
      </section>
      <OriginSection lineage={lineage} />

      {relevantOutcomes.length > 0 && (
        <section aria-labelledby="relevant-movement-heading">
          <SectionHeading title="Relevant document movement" />
          <p className="mb-2 text-xs text-ink-muted">Measured from recorded operator inputs and outputs. Counterfactual replay is shown separately below.</p>
          <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
            <table className="w-full text-left text-xs">
              <thead className="bg-surface-muted"><tr><th className="p-2">Document</th><th className="p-2">Pipeline</th><th className="p-2">Measured outcome</th><th className="p-2">First loss operator</th><th className="p-2">Evidence</th></tr></thead>
              <tbody>{relevantOutcomes.map((row) => (
                <tr key={`${row.traceId}:${row.docId}`} className="border-t border-slate-200 dark:border-slate-700">
                  <td className="p-2"><a className="font-mono text-indigo-700 dark:text-indigo-300 hover:underline" href={`#/runs/${encodeURIComponent(runId)}/queries/${encodeURIComponent(queryId)}/candidates/${encodeURIComponent(row.docId)}`}>{row.docId}</a></td>
                  <td className="p-2 font-mono">{row.pipelineId}</td>
                  <td className="p-2">{row.outcome.replace(/_/g, ' ')}</td>
                  <td className="p-2 font-mono">{row.operatorId ?? 'not applicable'}</td>
                  <td className="p-2">measured</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </section>
      )}

      {evidence.evidence_health.warnings.length > 0 && (
        <StatusPanel kind="partial" title="Evidence health: partial" message={
          <ul className="list-disc pl-4">
            {evidence.evidence_health.warnings.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        } />
      )}

      {evidence.diagnostics.some((diagnostic) => (diagnostic.diagnostic_evidence?.length ?? 0) > 0) && (
        <div>
          <SectionHeading title="Diagnostic evidence" />
          <div className="space-y-2">
            {evidence.diagnostics.flatMap((diagnostic) => (diagnostic.diagnostic_evidence ?? []).map((item) => (
              <div key={`${diagnostic.pipeline_id}:${item.label}`} className="rounded border border-gray-200 p-2 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono font-semibold">{item.label}</span>
                  <span className="rounded border px-1.5 py-0.5 text-[10px] uppercase">{item.evidence_class}</span>
                  <span className="text-ink-faint">{diagnostic.pipeline_id}</span>
                </div>
                <p className="mt-1 text-ink-muted">{item.reason}</p>
                <p className="mt-1 text-[10px] text-ink-faint">
                  method: {item.method}{item.threshold ? ` · threshold: ${item.threshold}` : ''}
                </p>
              </div>
            )))}
          </div>
        </div>
      )}

      {queryTraces.length === 0 ? (
        <StatusPanel kind="unavailable" title="Operator evidence unavailable" message="No operator-level trace data exists for this query. The run may predate V2 tracing, or the query may not be present in this run." />
      ) : (
        <div>
          <SectionHeading title="Evaluation traces & stage transitions" />
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
                      <span className="text-xs text-ink-muted">{trace.status} · {(trace.total_latency_ms ?? trace.timing?.wall_clock_ms ?? 0).toFixed(1)}ms</span>
                      <button
                        type="button"
                        onClick={() => setReplayFor(replayFor === trace.trace_id ? null : trace.trace_id)}
                        className="text-[10px] px-1.5 py-0.5 rounded border border-gray-200 dark:border-slate-700 text-ink-muted hover:text-indigo-600 hover:border-indigo-300"
                      >
                        {replayFor === trace.trace_id ? 'Hide recorded replay' : 'Recorded replay ▶'}
                      </button>
                    </div>
                  </div>
                  <TraceWaterfall
                    spans={trace.spans}
                    onSelectOp={(opId) => setSelected({ traceId: trace.trace_id, opId })}
                  />
                  {replayFor === trace.trace_id && (
                    <div className="mt-3 border-t border-gray-100 dark:border-slate-800 pt-3">
                      <SectionHeading title="Recorded trace step-through" />
                      <p className="mb-2 text-xs text-ink-muted">This replays recorded candidate transitions; it does not re-execute the production pipeline.</p>
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
                            href={`#/runs/${encodeURIComponent(runId)}/queries/${encodeURIComponent(queryId)}/candidates/${encodeURIComponent(docId)}`}
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
      <RecommendationsSection recommendations={evidence.findings} />
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
          Test Set scenario <span className="font-mono">{forge.scenario_id}</span> ({forge.scenario_type}, {forge.difficulty_label}) —{' '}
          {forge.positive_doc_ids?.length ? `${forge.positive_doc_ids.length} positive doc(s)` : 'no positive docs recorded'}.{' '}
          {forge.evidence_summary && <span>{forge.evidence_summary}</span>}{' '}
          <a href={`#/test-sets/${encodeURIComponent(forge.dataset_id)}`} className="text-indigo-700 underline underline-offset-2">
            View Test Set →
          </a>
        </div>
      ) : (
        <NoData label={`No Test Set origin recorded${lineage.origin?.dataset_name ? ` — from dataset "${lineage.origin.dataset_name}"` : ''}.`} />
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
                href={`#/runs/${encodeURIComponent(runId)}/queries/${encodeURIComponent(queryId)}/diff?against=${encodeURIComponent(ev.run_id)}`}
                className="text-indigo-700 underline underline-offset-2"
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
    { label: 'Recorded-output replay', docs: diff.without_operator },
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
        <span className="text-ink-muted">evidence: {diff.evidence_class}</span>
      </div>
      {diff.result_status === 'indeterminate' && (
        <div className="mb-2 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-900" role="status">
          Replay unavailable: {diff.reason ?? 'this operator path cannot be replayed.'}
          {diff.unsupported_descendants.length > 0 && ` Unsupported descendants: ${diff.unsupported_descendants.join(', ')}.`}
        </div>
      )}
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
