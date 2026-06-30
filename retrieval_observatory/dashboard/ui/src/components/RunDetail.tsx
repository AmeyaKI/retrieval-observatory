import { useEffect, useMemo, useState } from 'react'
import { fetchMetrics, fetchBaselines, fetchRunOverview, MetricsMap, Run, RunOverview } from '../api'
import MetricsTable from './MetricsTable'
import RecallCurve from './RecallCurve'
import RecallFunnel from './RecallFunnel'
import LatencyChart from './LatencyChart'
import SegmentBreakdown from './SegmentBreakdown'
import StagePipelineFlow from './StagePipelineFlow'
import VerdictCard from './VerdictCard'
import TradeoffScatter from './TradeoffScatter'
import ExperimentOverview from './ExperimentOverview'
import QueryExplorer from './QueryExplorer'
import StageCombinationMatrix from './StageCombinationMatrix'
import DashboardGuide from './DashboardGuide'
import DataQualityWarnings from './DataQualityWarnings'
import StressTestResults from './StressTestResults'
import { MetricTooltip } from './MetricTooltip'
import SegmentOperatorGrid from './SegmentOperatorGrid'
import OperatorInspector from './OperatorInspector'
import QueryWinnerTable from './QueryWinnerTable'

interface Props {
  run: Run
  dbId: string
  wide?: boolean
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <div className="mb-3">
        <h2 className="text-base font-semibold text-gray-800">{title}</h2>
        {subtitle && <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </section>
  )
}

function extractDatasetName(run: Run): string {
  try {
    const cfg = JSON.parse(run.config_json)
    return cfg?.dataset?.name ?? ''
  } catch {
    return ''
  }
}

// Infer a sensible default latency budget from the data (P75 of observed latencies)
function inferLatencyBudget(metrics: MetricsMap): number {
  const latencies = Object.values(metrics)
    .filter((e) => e.metric_name === 'latency_p50' && e.stage_index < 0)
    .map((e) => e.mean)
  if (latencies.length === 0) return 2000
  const sorted = [...latencies].sort((a, b) => a - b)
  const inferred = Math.round(sorted[Math.floor(sorted.length * 0.75)] * 2)
  return Math.min(30000, Math.max(100, inferred))
}

export default function RunDetail({ run, dbId, wide = false }: Props) {
  const [metrics, setMetrics] = useState<MetricsMap | null>(null)
  const [overview, setOverview] = useState<RunOverview | null>(null)
  const [baselines, setBaselines] = useState<Record<string, number>>({})
  const [error, setError] = useState<string | null>(null)

  // Tradeoff explorer slider state — lifted here so VerdictCard and TradeoffScatter stay in sync
  const [latencyBudgetMs, setLatencyBudgetMs] = useState<number>(2000)
  const [minQualityDelta, setMinQualityDelta] = useState<number>(0.02)

  const datasetName = extractDatasetName(run)

  useEffect(() => {
    setMetrics(null)
    setOverview(null)
    setError(null)
    fetchMetrics(dbId, run.run_id)
      .then((m) => {
        setMetrics(m)
        setLatencyBudgetMs(inferLatencyBudget(m))
      })
      .catch((e) => setError(e.message))
    fetchRunOverview(dbId, run.run_id)
      .then((ov) => {
        setOverview(ov)
        if (typeof ov.manifest?.latency_budget_ms === 'number') {
          setLatencyBudgetMs(ov.manifest.latency_budget_ms)
        }
      })
      .catch(() => setOverview(null))
  }, [dbId, run.run_id])

  useEffect(() => {
    if (datasetName) {
      fetchBaselines(datasetName)
        .then(setBaselines)
        .catch(() => setBaselines({}))
    }
  }, [datasetName])

  const stageContributions = useMemo(() => overview?.stage_contributions ?? [], [overview])

  const pipelineCount = useMemo(() => {
    if (!metrics) return 0
    return new Set(
      Object.values(metrics)
        .filter((e) => e.stage_index >= 0)
        .map((e) => e.pipeline_id)
    ).size
  }, [metrics])

  if (error) {
    return (
      <div className="p-6">
        <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
      </div>
    )
  }

  if (!metrics) {
    return (
      <div className="p-6 flex items-center gap-2 text-gray-400 text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 border-t-indigo-600" />
        Loading metrics...
      </div>
    )
  }

  const showTradeoffExplorer = pipelineCount >= 2

  return (
    <div className={`p-6 ${wide ? 'max-w-full' : 'max-w-5xl'}`}>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">{run.experiment_name}</h1>
          <p className="text-sm text-gray-500 font-mono mt-0.5">{run.run_id}</p>
          {run.forge_dataset_id && (
            <p className="text-xs text-amber-800 mt-1">
              Originating Forge dataset:{' '}
              <a href={`#/forge/${encodeURIComponent(run.forge_dataset_id)}`} className="underline decoration-amber-400 hover:text-amber-700">
                {run.forge_dataset_id}
              </a>
            </p>
          )}
        </div>
      </div>

      <DashboardGuide />

      {Object.values(metrics).some((e) => e.stage_index >= 0) && (
        <Section title="Pipeline Architecture" subtitle="Stage-by-stage flow of your retrieval pipeline with per-stage quality and latency">
          <StagePipelineFlow metrics={metrics} topology={overview?.pipeline_topology} />
        </Section>
      )}

      <Section title="Experiment Overview" subtitle="Headline winner, query difficulty distribution, failure label summary, and classifier calibration">
        <ExperimentOverview dbId={dbId} runId={run.run_id} />
      </Section>

      {/* Tradeoff explorer sliders — shown when comparing 2+ pipelines */}
      {showTradeoffExplorer && (
        <div className="mb-4 p-4 border border-indigo-100 rounded-lg bg-indigo-50/40">
          <div className="flex items-center gap-2 mb-3">
            <div className="text-sm font-semibold text-gray-700">Tradeoff Explorer</div>
            <span className="text-xs text-gray-400">— adjust thresholds to see which pipeline wins under your constraints</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-gray-700 block mb-1">
                My latency budget: <span className="font-mono font-bold text-indigo-700">{latencyBudgetMs}ms</span>
                <span className="ml-1 text-gray-400">(P50 per query, auto = P75×2)</span>
                <MetricTooltip text="Default latency budget is inferred as P75×2 from observed end-to-end P50 latencies. You can override it." />
              </label>
              <input
                type="range"
                min={100}
                max={30000}
                step={50}
                value={latencyBudgetMs}
                onChange={(e) => setLatencyBudgetMs(Number(e.target.value))}
                className="w-full accent-indigo-600"
              />
              <div className="flex justify-between text-[10px] text-gray-400 mt-0.5">
                <span>100ms</span><span>30,000ms (30s)</span>
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-700 block mb-1">
                Min quality gain to justify cost: <span className="font-mono font-bold text-indigo-700">{minQualityDelta.toFixed(2)}</span>
                <span className="ml-1 text-gray-400">(NDCG@10)</span>
              </label>
              <input
                type="range"
                min={0}
                max={0.2}
                step={0.005}
                value={minQualityDelta}
                onChange={(e) => setMinQualityDelta(Number(e.target.value))}
                className="w-full accent-indigo-600"
              />
              <div className="flex justify-between text-[10px] text-gray-400 mt-0.5">
                <span>0.00 (any gain)</span><span>0.20 (large gain)</span>
              </div>
            </div>
          </div>
        </div>
      )}

      <VerdictCard
        metrics={metrics}
        stageContributions={stageContributions}
        latencyBudgetMs={latencyBudgetMs}
        minQualityDelta={minQualityDelta}
      />

      {overview && <DataQualityWarnings warnings={overview.warnings} />}

      <Section title="Metrics Summary" subtitle="NDCG, Recall, MRR, MAP, and latency across all pipelines — with significance tests for stage pairs">
        <MetricsTable
          metrics={metrics}
          baselines={baselines}
          latencyBudgetMs={latencyBudgetMs}
          diagnosticsByPipeline={overview?.diagnostics?.by_pipeline}
          stageContributions={stageContributions}
        />
      </Section>

      <Section title="Recall@K Curves" subtitle="How much of the relevant content is retrieved as K (candidate count) increases">
        <RecallCurve metrics={metrics} baselines={baselines} />
      </Section>

      <Section title="Stage Recall Funnel" subtitle="How recall and NDCG change at each pipeline stage — a drop after reranking is normal since fewer docs are kept">
        <RecallFunnel metrics={metrics} />
      </Section>

      <Section title="Latency Breakdown" subtitle="P50/P95/P99 latency per pipeline stage — P50 is median, P95 captures tail latency">
        <LatencyChart metrics={metrics} />
      </Section>

      <Section title="Quality vs. Latency" subtitle="Scatter plot of each pipeline's NDCG vs P50 latency — Pareto-optimal pipelines are those where no other pipeline is better on both dimensions">
        <TradeoffScatter dbId={dbId} runId={run.run_id} latencyBudgetMs={latencyBudgetMs} />
      </Section>

      <Section title="Stage Combination Matrix" subtitle="Compact view of all pipeline configurations: quality, latency, and cost side-by-side">
        <StageCombinationMatrix dbId={dbId} runId={run.run_id} latencyBudgetMs={latencyBudgetMs} />
      </Section>

      <Section title="Operator Attribution Grid" subtitle="Per-operator attribution by segment with explicit measured/not-applicable states">
        <SegmentOperatorGrid dbId={dbId} runId={run.run_id} />
      </Section>

      <Section title="Operator Inspector" subtitle="Replay-tier and per-segment operator details">
        <OperatorInspector dbId={dbId} runId={run.run_id} />
      </Section>

      <Section title="Per-query Winners" subtitle="Cross-pipeline winner per query; unjudged rows are labeled explicitly">
        <QueryWinnerTable dbId={dbId} runId={run.run_id} />
      </Section>

      <Section title="Query Explorer" subtitle="Drill into individual queries — see failure labels, missing relevant docs, and predicted vs actual difficulty">
        <QueryExplorer dbId={dbId} runId={run.run_id} />
      </Section>

      <Section title="Performance by Corpus Density" subtitle="NDCG@10 grouped by number of relevant documents per query — harder when more docs are relevant">
        <SegmentBreakdown dbId={dbId} runId={run.run_id} field="n_relevant" targetMetric="ndcg" />
      </Section>

      {/* Renders only when the run's queries carry Forge metadata (scenario_type / difficulty_label). */}
      <StressTestResults dbId={dbId} runId={run.run_id} />
    </div>
  )
}
