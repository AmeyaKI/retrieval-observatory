import QueryWinnerTable from './QueryWinnerTable'
import QueryExplorer from './QueryExplorer'
import SegmentBreakdown from './SegmentBreakdown'
import StressTestResults from './StressTestResults'

// Per-query exploration, winners, and segment breakdowns. Per-stage attribution
// (SegmentOperatorGrid/OperatorInspector) now lives on its own page, RunAttributionPage.
export default function RunQueriesPage({ dbId, runId }: { dbId: string; runId: string }) {
  return (
    <div className="space-y-8">
      <QueryWinnerTable dbId={dbId} runId={runId} />
      <QueryExplorer dbId={dbId} runId={runId} />
      <SegmentBreakdown dbId={dbId} runId={runId} field="n_relevant" targetMetric="ndcg" />
      <StressTestResults dbId={dbId} runId={runId} />
    </div>
  )
}
