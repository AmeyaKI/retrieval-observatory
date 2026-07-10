import { Run } from '../api'
import { useRunMetrics } from '../hooks/useRunMetrics'
import MetricsTable from './MetricsTable'
import RecallCurve from './RecallCurve'
import RecallFunnel from './RecallFunnel'
import StageCombinationMatrix from './StageCombinationMatrix'
import { PipelineDisplayMeta } from '../utils/stageLabels'

export default function RunQualityPage({ run, dbId }: { run: Run; dbId: string }) {
  const { metrics, overview, baselines, error, latencyBudgetMs } = useRunMetrics(dbId, run.run_id, run.config_json)
  const stageContributions = overview?.stage_contributions ?? []
  const displayMeta = (overview?.manifest ?? null) as PipelineDisplayMeta | null

  if (error) return <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
  if (!metrics) {
    return (
      <div className="flex items-center gap-2 text-ink-faint text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 dark:border-slate-600 border-t-indigo-600" />
        Loading quality metrics...
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <div>
        <h3 className="text-sm font-semibold text-ink mb-2">Metrics Summary</h3>
        <MetricsTable metrics={metrics} baselines={baselines} latencyBudgetMs={latencyBudgetMs} diagnosticsByPipeline={overview?.diagnostics?.by_pipeline} stageContributions={stageContributions} />
      </div>
      <div>
        <h3 className="text-sm font-semibold text-ink mb-2">Recall@K Curves</h3>
        <RecallCurve metrics={metrics} baselines={baselines} />
      </div>
      <div>
        <h3 className="text-sm font-semibold text-ink mb-2">Stage Recall Funnel</h3>
        <RecallFunnel metrics={metrics} displayMeta={displayMeta} />
      </div>
      <div>
        <h3 className="text-sm font-semibold text-ink mb-2">Stage Combination Matrix</h3>
        <StageCombinationMatrix dbId={dbId} runId={run.run_id} latencyBudgetMs={latencyBudgetMs} />
      </div>
    </div>
  )
}
