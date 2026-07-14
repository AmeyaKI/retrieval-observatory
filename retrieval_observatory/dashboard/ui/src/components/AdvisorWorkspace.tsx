import { useEffect, useState } from 'react'
import {
  DemoContext,
  fetchAdvisorRecommendations,
  fetchAdvisorRegressions,
  fetchAdvisorReliability,
  fetchAdvisorReliabilityHistory,
  fetchDemoContext,
  fetchDbs,
  fetchRuns,
  Recommendation,
  RegressionFinding,
  ReliabilityScore,
  Run,
  ReliabilityHistoryPoint,
} from '../api'
import WorkspaceGlossaryLink from './WorkspaceGlossaryLink'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <div className="mb-3">
        <h2 className="text-base font-semibold text-gray-800 dark:text-slate-100">{title}</h2>
        {subtitle && <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </section>
  )
}

type AdvisorView = 'recommendations' | 'regressions'

export default function AdvisorWorkspace() {
  const [dbId, setDbId] = useState<string | null>(null)
  const [view, setView] = useState<AdvisorView>('recommendations')
  const [runs, setRuns] = useState<Run[]>([])
  const [demoContext, setDemoContext] = useState<DemoContext | null>(null)
  const [selectedRun, setSelectedRun] = useState('')
  const [baseline, setBaseline] = useState('')
  const [candidate, setCandidate] = useState('')
  const [recommendations, setRecommendations] = useState<Recommendation[]>([])
  const [regressions, setRegressions] = useState<RegressionFinding[]>([])
  const [reliability, setReliability] = useState<ReliabilityScore | null>(null)
  const [history, setHistory] = useState<ReliabilityHistoryPoint[]>([])
  const [showAllHistory, setShowAllHistory] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchDbs()
      .then((dbs) => {
        if (dbs.length > 0) setDbId(dbs[0].db_id)
      })
      .catch((e) => setError(String(e)))
    fetchDemoContext()
      .then((ctx) => {
        if (ctx.baseline_run_id) setDemoContext(ctx)
      })
      .catch(() => setDemoContext(null))
  }, [])

  useEffect(() => {
    if (!dbId) return
    fetchRuns(dbId).then(setRuns).catch((e) => setError(String(e)))
  }, [dbId])

  useEffect(() => {
    if (!demoContext?.candidate_run_id || runs.length === 0) return
    setSelectedRun(demoContext.candidate_run_id)
    setBaseline(demoContext.baseline_run_id || '')
    setCandidate(demoContext.candidate_run_id)
    setView('regressions')
  }, [demoContext, runs])

  useEffect(() => {
    if (!baseline || !candidate) return
    setError(null)
    if (!dbId) return
    fetchAdvisorRegressions(dbId, baseline, candidate)
      .then((res) => setRegressions(res.regressions))
      .catch((e) => setError(String(e)))
  }, [baseline, candidate, dbId])

  useEffect(() => {
    if (!selectedRun || !dbId) return
    setError(null)
    Promise.all([
      fetchAdvisorRecommendations(dbId, selectedRun),
      fetchAdvisorReliability(dbId, selectedRun),
      fetchAdvisorReliabilityHistory(dbId, selectedRun),
    ])
      .then(([recRes, relRes, histRes]) => {
        setRecommendations(recRes.recommendations)
        setReliability(relRes)
        setHistory(histRes.history)
      })
      .catch((e) => setError(String(e)))
  }, [dbId, selectedRun])

  const loadRegressions = () => {
    if (!baseline || !candidate || !dbId) return
    setError(null)
    fetchAdvisorRegressions(dbId, baseline, candidate)
      .then((res) => setRegressions(res.regressions))
      .catch((e) => setError(String(e)))
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <header className="shrink-0 border-b border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-6 py-4">
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-lg font-semibold text-violet-800">Advisor</h1>
          <WorkspaceGlossaryLink className="text-[11px] text-violet-700 underline decoration-violet-300" />
        </div>
        <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5">
          Rule-based recommendations with cited evidence — heuristics, not guarantees.
        </p>
        {demoContext?.baseline_run_id && (
          <div className="mt-2 rounded-lg border border-violet-200 bg-violet-50/80 px-3 py-2 text-xs text-violet-900">
            Demo DB — baseline {demoContext.experiment_names?.baseline ?? demoContext.baseline_run_id} vs candidate {demoContext.experiment_names?.candidate ?? demoContext.candidate_run_id}. Regressions load automatically.
          </div>
        )}
        {reliability && (
          <div className="mt-3 rounded-lg border border-violet-200 bg-violet-50 p-3 text-xs">
            <div className="flex items-center gap-2">
              <p className="font-semibold text-violet-900">
                Reliability score: {(reliability.value * 100).toFixed(0)}%
              </p>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-100 text-violet-700 border border-violet-200">heuristic</span>
              <MetricTooltip text={METRIC_GLOSSARY.reliability_components} />
            </div>
            <p className="text-[11px] text-gray-600 dark:text-slate-300 mt-1">
              Unweighted average of four components (25% each). Not a calibrated metric — use as a directional indicator.
            </p>
            {reliability.notes && reliability.notes.length > 0 && (
              <div className="mt-1 space-y-0.5">
                {reliability.notes.map((note, i) => (
                  <p key={i} className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-0.5">
                    ⚠ {note}
                  </p>
                ))}
              </div>
            )}
            <p className="text-[11px] text-gray-600 dark:text-slate-300 mt-1">
              Reference scale: &ge;85% strong, 70–84% watchlist, &lt;70% poor.
            </p>
            <div className="flex flex-wrap gap-3 mt-1 text-gray-700 dark:text-slate-200">
              {Object.entries(reliability.components).map(([k, v]) => (
                <span key={k}>{k.replace(/_/g, ' ')}: {(v * 100).toFixed(0)}%</span>
              ))}
            </div>
            <details className="mt-2">
              <summary className="cursor-pointer text-[11px] text-violet-800 font-medium">Show component formulas</summary>
              <p className="mt-1 text-[11px] text-gray-700 dark:text-slate-200">
                recall_at_10 = mean Recall@10 across pipelines; low_failure_rate = 1 − failure_label_rate; latency_headroom = budget headroom from latency_p95 (fallback 0.5 if no budget set); diagnostic_health = 1 − unstable_rate.
              </p>
            </details>
          </div>
        )}
      </header>

      <div className="shrink-0 flex gap-2 px-6 py-2 border-b border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900">
        {(['recommendations', 'regressions'] as AdvisorView[]).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setView(v)}
            className={`px-3 py-1.5 rounded text-xs font-medium capitalize ${
              view === v ? 'bg-violet-100 text-violet-800' : 'text-gray-500 dark:text-slate-400 hover:bg-gray-50'
            }`}
          >
            {v === 'regressions' ? 'Regression Center' : v}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto p-6">
        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

        {view === 'recommendations' && (
          <>
            <div className="mb-4">
              <label className="text-xs text-gray-500 dark:text-slate-400 block mb-1">Run</label>
              <select
                className="text-sm border border-gray-200 dark:border-slate-700 rounded px-2 py-1.5"
                value={selectedRun}
                onChange={(e) => setSelectedRun(e.target.value)}
              >
                <option value="">Select a run…</option>
                {runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.experiment_name} ({r.run_id})
                  </option>
                ))}
              </select>
            </div>
            <Section title="Recommendations" subtitle="Ranked by priority">
              {recommendations.length === 0 ? (
                <p className="text-xs text-gray-400 dark:text-slate-500">Select a run to see recommendations.</p>
              ) : (
                <div className="space-y-3">
                  {recommendations.map((rec, i) => (
                    <div key={i} className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-medium text-gray-900 dark:text-slate-100">{rec.action}</p>
                        <span className="text-[10px] px-1.5 py-0.5 rounded border border-violet-200 bg-violet-50 text-violet-700 font-semibold">
                          Priority {rec.priority}
                        </span>
                      </div>
                      <p className="text-xs text-gray-600 dark:text-slate-300 mt-1">{rec.rationale}</p>
                      {rec.estimated_quality_improvement != null ? (
                        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
                          <span className="font-semibold text-emerald-700 dark:text-emerald-400">
                            +{(rec.estimated_quality_improvement * 100).toFixed(1)}% {rec.quality_metric ?? ''}
                            {rec.estimated_quality_ci && (
                              <span className="font-normal text-gray-400 dark:text-slate-500">
                                {' '}
                                [{(rec.estimated_quality_ci[0] * 100).toFixed(1)}, {(rec.estimated_quality_ci[1] * 100).toFixed(1)}]
                              </span>
                            )}
                          </span>
                          {rec.estimated_latency_increase_ms != null && (
                            <span className="text-gray-500 dark:text-slate-400">
                              +{rec.estimated_latency_increase_ms.toFixed(0)}ms latency
                            </span>
                          )}
                          {rec.implementation_effort && (
                            <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300">
                              effort: {rec.implementation_effort}
                            </span>
                          )}
                          {rec.confidence != null && (
                            <span className="text-gray-500 dark:text-slate-400">confidence {(rec.confidence * 100).toFixed(0)}%</span>
                          )}
                          {rec.affected_query_categories && rec.affected_query_categories.length > 0 && (
                            <span className="text-gray-400 dark:text-slate-500">
                              on {rec.affected_query_categories.join(', ')} queries
                            </span>
                          )}
                        </div>
                      ) : (
                        <p className="mt-2 text-[11px] text-gray-400 dark:text-slate-500 italic">not estimated</p>
                      )}
                      <ul className="mt-2 text-[11px] text-gray-500 dark:text-slate-400 list-disc pl-4">
                        {rec.evidence.map((ev, j) => (
                          <li key={j}>{ev}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </Section>
            {history.length > 1 && (
              <Section title="Reliability trend" subtitle="Snapshots recorded when reliability is computed">
                <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-3 text-xs space-y-1">
                  {(showAllHistory ? history : history.slice(0, 8)).map((h) => (
                    <div key={h.recorded_at} className="flex justify-between text-gray-600 dark:text-slate-300">
                      <span>{new Date(h.recorded_at).toLocaleString()}</span>
                      <span className="font-mono font-semibold">{(h.value * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                  {history.length > 8 && (
                    <button
                      type="button"
                      onClick={() => setShowAllHistory((v) => !v)}
                      className="mt-2 text-xs text-violet-700 hover:text-violet-900"
                    >
                      {showAllHistory ? 'Show fewer' : `Show all ${history.length} snapshots`}
                    </button>
                  )}
                </div>
              </Section>
            )}
          </>
        )}

        {view === 'regressions' && (
          <Section title="Regression Center" subtitle="Baseline vs candidate with BH-adjusted q-values">
            <div className="flex flex-wrap gap-3 mb-4">
              <select className="text-sm border rounded px-2 py-1.5" value={baseline} onChange={(e) => setBaseline(e.target.value)}>
                <option value="">Baseline run…</option>
                {runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>{r.run_id}</option>
                ))}
              </select>
              <select className="text-sm border rounded px-2 py-1.5" value={candidate} onChange={(e) => setCandidate(e.target.value)}>
                <option value="">Candidate run…</option>
                {runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>{r.run_id}</option>
                ))}
              </select>
              <button
                type="button"
                onClick={loadRegressions}
                className="px-3 py-1.5 rounded bg-violet-600 text-white text-xs font-medium"
              >
                Compare
              </button>
            </div>
            {regressions.length === 0 ? (
              <p className="text-xs text-gray-400 dark:text-slate-500">No significant regressions (or compare not run yet).</p>
            ) : (
              <table className="w-full text-xs border border-gray-200 dark:border-slate-700 rounded-lg overflow-hidden">
                <thead className="bg-gray-50 dark:bg-slate-800/60">
                  <tr>
                    <th className="text-left px-3 py-2">Metric</th>
                    <th className="text-right px-3 py-2">Before</th>
                    <th className="text-right px-3 py-2">After</th>
                    <th className="text-right px-3 py-2">
                      q-value
                      <MetricTooltip text="BH-adjusted q-value (FDR-controlled p-value). Treat q < 0.05 as statistically significant after multiple-comparison correction." />
                    </th>
                    <th className="text-left px-3 py-2">Severity</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {regressions.map((r) => (
                    <tr key={r.metric}>
                      <td className="px-3 py-2 font-mono text-[10px]">{r.metric}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.before.toFixed(4)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.after.toFixed(4)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.q_value.toFixed(4)}</td>
                      <td className="px-3 py-2 capitalize">{r.severity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
        )}
      </div>
    </div>
  )
}
