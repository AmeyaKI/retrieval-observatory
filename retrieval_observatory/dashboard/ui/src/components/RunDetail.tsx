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

interface Props {
  run: Run
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="text-base font-semibold text-gray-800 mb-3">{title}</h2>
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
  return Math.round(sorted[Math.floor(sorted.length * 0.75)] * 2)
}

export default function RunDetail({ run }: Props) {
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
    fetchMetrics(run.run_id)
      .then((m) => {
        setMetrics(m)
        setLatencyBudgetMs(inferLatencyBudget(m))
      })
      .catch((e) => setError(e.message))
    fetchRunOverview(run.run_id)
      .then(setOverview)
      .catch(() => setOverview(null))
  }, [run.run_id])

  useEffect(() => {
    if (datasetName) {
      fetchBaselines(datasetName)
        .then(setBaselines)
        .catch(() => setBaselines({}))
    }
  }, [datasetName])

  const stageContributions = useMemo(() => overview?.stage_contributions ?? [], [overview])

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

  const hasContributions = stageContributions.length > 0

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">{run.experiment_name}</h1>
          <p className="text-sm text-gray-500 font-mono mt-0.5">{run.run_id}</p>
        </div>
      </div>

      {Object.values(metrics).some((e) => e.stage_index > 0) && (
        <Section title="Pipeline Architecture">
          <StagePipelineFlow metrics={metrics} />
        </Section>
      )}

      <Section title="Experiment Overview">
        <ExperimentOverview runId={run.run_id} />
      </Section>

      {/* Tradeoff explorer sliders — shown when there are stage pairs to compare */}
      {hasContributions && (
        <div className="mb-4 p-4 border border-gray-200 rounded-lg bg-gray-50">
          <div className="text-sm font-semibold text-gray-700 mb-3">Tradeoff Explorer</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-gray-600 block mb-1">
                Latency budget per query: <span className="font-mono font-semibold text-gray-900">{latencyBudgetMs}ms</span>
              </label>
              <input
                type="range"
                min={0}
                max={10000}
                step={50}
                value={latencyBudgetMs}
                onChange={(e) => setLatencyBudgetMs(Number(e.target.value))}
                className="w-full accent-indigo-600"
              />
              <div className="flex justify-between text-[10px] text-gray-400 mt-0.5">
                <span>0ms</span><span>10,000ms</span>
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-600 block mb-1">
                Minimum quality improvement: <span className="font-mono font-semibold text-gray-900">{minQualityDelta.toFixed(2)}</span>
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
                <span>0.00</span><span>0.20</span>
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

      <Section title="Metrics Summary">
        <MetricsTable metrics={metrics} baselines={baselines} />
      </Section>

      <Section title="Recall@K Curves">
        <RecallCurve metrics={metrics} baselines={baselines} />
      </Section>

      <Section title="Stage Recall Funnel">
        <RecallFunnel metrics={metrics} />
      </Section>

      <Section title="Latency Percentiles">
        <LatencyChart metrics={metrics} />
      </Section>

      <Section title="Quality vs. Latency Tradeoff">
        <TradeoffScatter metrics={metrics} latencyBudgetMs={latencyBudgetMs} />
      </Section>

      <Section title="Stage Combination Matrix">
        <StageCombinationMatrix runId={run.run_id} />
      </Section>

      <Section title="Query Explorer">
        <QueryExplorer runId={run.run_id} />
      </Section>

      <Section title="NDCG@10 by Number of Relevant Docs">
        <SegmentBreakdown runId={run.run_id} field="n_relevant" targetMetric="ndcg" />
      </Section>
    </div>
  )
}
