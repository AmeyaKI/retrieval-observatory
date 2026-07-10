import { Run } from '../api'
import { useRunMetrics } from '../hooks/useRunMetrics'
import TradeoffScatter from './TradeoffScatter'
import LatencyChart from './LatencyChart'
import { PipelineDisplayMeta } from '../utils/stageLabels'

export default function RunTradeoffsPage({ run, dbId }: { run: Run; dbId: string }) {
  const { metrics, overview, error, latencyBudgetMs } = useRunMetrics(dbId, run.run_id, run.config_json)
  const displayMeta = (overview?.manifest ?? null) as PipelineDisplayMeta | null

  if (error) return <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
  if (!metrics) {
    return (
      <div className="flex items-center gap-2 text-ink-faint text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 dark:border-slate-600 border-t-indigo-600" />
        Loading tradeoffs...
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <TradeoffScatter dbId={dbId} runId={run.run_id} latencyBudgetMs={latencyBudgetMs} />
      <div>
        <h3 className="text-sm font-semibold text-ink mb-2">Latency Breakdown</h3>
        <LatencyChart metrics={metrics} displayMeta={displayMeta} />
      </div>
    </div>
  )
}
