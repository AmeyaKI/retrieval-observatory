import { useEffect, useState } from 'react'
import { fetchAdvisorRecommendations, Recommendation, Run } from '../api'
import { useRunMetrics } from '../hooks/useRunMetrics'
import DashboardGuide from './DashboardGuide'
import RunManifestPanel from './RunManifestPanel'
import VerdictCard from './VerdictCard'
import DataQualityWarnings from './DataQualityWarnings'
import ExperimentOverview from './ExperimentOverview'
import { MetricTooltip } from './MetricTooltip'

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
    fetchAdvisorRecommendations(run.run_id)
      .then((r) => setRecommendations(r.recommendations))
      .catch(() => setRecommendations([]))
  }, [run.run_id])

  const stageContributions = overview?.stage_contributions ?? []
  const pipelineCount = metrics
    ? new Set(Object.values(metrics).filter((e) => e.stage_index >= 0).map((e) => e.pipeline_id)).size
    : 0
  const failureLabels = overview?.diagnostics?.failure_labels ?? {}
  const worstFailure = Object.entries(failureLabels).sort((a, b) => b[1] - a[1])[0]

  if (error) {
    return (
      <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
    )
  }
  if (!metrics) {
    return (
      <div className="flex items-center gap-2 text-ink-faint text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 dark:border-slate-600 border-t-indigo-600" />
        Loading overview...
      </div>
    )
  }

  const runHref = (page: string) => `#/benchmarks/run/${encodeURIComponent(run.run_id)}${page ? `/${page}` : ''}`

  return (
    <div className="space-y-6">
      <DashboardGuide />
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

        <a href={runHref('')} onClick={(e) => e.preventDefault()} className="block p-4 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900">
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
        </a>

        <a href={runHref('architecture')} className="block p-4 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-indigo-300 transition-colors">
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">Benchmark health</div>
          <div className="text-sm text-ink">{overview?.warnings?.length ?? 0} warning(s)</div>
          <div className="text-xs text-ink-muted mt-0.5">Inspect architecture & manifest →</div>
        </a>
      </div>
    </div>
  )
}
