import { useEffect, useState } from 'react'
import { fetchAdvisorRecommendations, Recommendation, Run } from '../api'
import { useRunMetrics } from '../hooks/useRunMetrics'
import RunManifestPanel from './RunManifestPanel'
import VerdictCard from './VerdictCard'
import DataQualityWarnings from './DataQualityWarnings'
import ExperimentOverview from './ExperimentOverview'
import { MetricTooltip } from './MetricTooltip'
import StatusPanel from './StatusPanel'

// The executive-summary landing page (RETOBS_FINER_PLAN_PHASE2.md / retobs_finer.md
// Pillar 1): overall quality, latency, biggest failures, recommendations, and benchmark
// health all visible without opening another page. Each tile is a *door* -- it links to
// the disclosure-spine page that explains it in depth.
export default function RunOverviewPage({ run, dbId }: { run: Run; dbId: string }) {
  const { metrics, overview, error, latencyBudgetMs, setLatencyBudgetMs } = useRunMetrics(
    dbId,
    run.run_id,
    run.config_json,
  )
  const [minQualityDelta, setMinQualityDelta] = useState(0.02)
  const [recommendations, setRecommendations] = useState<Recommendation[] | null>(null)

  useEffect(() => {
    fetchAdvisorRecommendations(dbId, run.run_id)
      .then((r) => setRecommendations(r.recommendations))
      .catch(() => setRecommendations([]))
  }, [dbId, run.run_id])

  const stageContributions = overview?.stage_contributions ?? []
  const pipelineCount = metrics
    ? new Set(Object.values(metrics).filter((e) => e.stage_index >= 0).map((e) => e.pipeline_id)).size
    : 0
  const failureLabels = overview?.diagnostics?.failure_labels ?? {}
  const worstFailure = Object.entries(failureLabels).sort((a, b) => b[1] - a[1])[0]

  if (error) {
    return <StatusPanel kind="error" title="Run evidence could not be loaded" message={error} />
  }
  if (!metrics) {
    return <StatusPanel kind="loading" message="Loading run conclusion and evidence…" />
  }
  if (Object.keys(metrics).length === 0) {
    return <StatusPanel kind="empty" title="No run metrics" message="This run has no persisted measurements to summarize." />
  }

  const runHref = (page: string) => `#/runs/${encodeURIComponent(run.run_id)}${page ? `/${page}` : ''}`
  const report = overview?.report

  return (
    <div className="space-y-6">
      {report && (
        <section aria-labelledby="run-conclusion" className="rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 p-5">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <h2 id="run-conclusion" className="text-lg font-semibold text-ink">Run conclusion</h2>
            <span className="rounded-full border border-slate-300 dark:border-slate-600 px-2 py-0.5 text-xs font-medium text-ink">
              Verdict: {report.verdict.replace(/_/g, ' ')}
            </span>
            <span className="rounded-full border border-slate-300 dark:border-slate-600 px-2 py-0.5 text-xs font-medium text-ink">
              Evidence: {report.evidence_health}
            </span>
          </div>
          <p className="text-sm text-ink mb-3">{report.conclusion}</p>
          {report.evidence_reasons.length > 0 && (
            <ul className="mb-3 list-disc pl-5 text-xs text-amber-800 dark:text-amber-300">
              {report.evidence_reasons.map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
          )}
          <div className="text-xs text-ink-muted">
            <strong className="text-ink">Next action:</strong> {report.next_action}
          </div>
          {report.affected_queries[0] && (
            <a
              className="mt-3 inline-flex text-sm font-medium text-indigo-700 dark:text-indigo-300 hover:underline"
              href={`${runHref('queries')}/${encodeURIComponent(report.affected_queries[0].query_id)}`}
            >
              Inspect first affected query →
            </a>
          )}
        </section>
      )}
      <RunManifestPanel overview={overview} />

      {pipelineCount >= 2 && (
        <div className="p-4 border border-indigo-100 dark:border-indigo-900 rounded-lg bg-indigo-50/40 dark:bg-indigo-950/30">
          <div className="flex items-center gap-2 mb-3">
            <div className="text-sm font-semibold text-ink">Tradeoff Explorer</div>
            <span className="text-xs text-ink-muted">— adjust thresholds to see which pipeline wins under your constraints</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-ink block mb-1">
                My latency budget: <span className="font-mono font-bold text-indigo-700 dark:text-indigo-300">{latencyBudgetMs}ms</span>
                <span className="ml-1 text-ink-faint">(end-to-end P50, auto = P75×2)</span>
                <MetricTooltip text="Default latency budget is inferred as P75×2 from observed end-to-end P50 latencies." />
              </label>
              <input type="range" min={100} max={30000} step={50} value={latencyBudgetMs} onChange={(e) => setLatencyBudgetMs(Number(e.target.value))} className="w-full accent-indigo-600" />
            </div>
            <div>
              <label className="text-xs text-ink block mb-1">
                Min quality gain: <span className="font-mono font-bold text-indigo-700 dark:text-indigo-300">{minQualityDelta.toFixed(2)}</span> NDCG@10
              </label>
              <input type="range" min={0} max={0.2} step={0.005} value={minQualityDelta} onChange={(e) => setMinQualityDelta(Number(e.target.value))} className="w-full accent-indigo-600" />
            </div>
          </div>
        </div>
      )}

      <VerdictCard metrics={metrics} stageContributions={stageContributions} latencyBudgetMs={latencyBudgetMs} minQualityDelta={minQualityDelta} />
      {overview && <DataQualityWarnings warnings={overview.warnings} />}
      <ExperimentOverview dbId={dbId} runId={run.run_id} />

      {/* Doors into the disclosure spine */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <a href={runHref('queries')} className="block p-4 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-indigo-300 transition-colors">
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">Biggest failures</div>
          {worstFailure ? (
            <>
              <div className="text-sm font-medium text-ink">{worstFailure[0]}</div>
              <div className="text-xs text-ink-muted mt-0.5">{worstFailure[1]} queries affected — inspect in Queries →</div>
            </>
          ) : (
            <div className="text-sm text-ink-muted">No failure labels recorded</div>
          )}
        </a>

        <a href={runHref('queries')} className="block p-4 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-indigo-300 transition-colors">
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">Recommendations</div>
          {recommendations === null ? (
            <div className="text-sm text-ink-muted">Loading…</div>
          ) : recommendations.length === 0 ? (
            <div className="text-sm text-ink-muted">No recommendations for this run</div>
          ) : (
            <ul className="text-xs text-ink space-y-1">
              {recommendations.slice(0, 2).map((r, i) => (
                <li key={i} className="truncate" title={r.action}>• {r.action}</li>
              ))}
            </ul>
          )}
          <div className="text-xs text-ink-muted mt-1">Open supporting query evidence →</div>
        </a>

        <a href={runHref('architecture')} className="block p-4 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-indigo-300 transition-colors">
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">Evidence health</div>
          <div className="text-sm text-ink">{overview?.warnings?.length ?? 0} warning(s)</div>
          <div className="text-xs text-ink-muted mt-0.5">Inspect architecture & manifest →</div>
        </a>
      </div>
    </div>
  )
}
