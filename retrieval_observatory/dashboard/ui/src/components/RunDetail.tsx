import { useEffect, useMemo, useState } from 'react'
import { fetchMetrics, fetchBaselines, fetchRunOverview, MetricsMap, Run, RunOverview } from '../api'
import MetricsTable from './MetricsTable'
import RecallCurve from './RecallCurve'
import RecallFunnel from './RecallFunnel'
import LatencyChart from './LatencyChart'
import SegmentBreakdown from './SegmentBreakdown'
import PipelineDagView from './PipelineDagView'
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
import RunSectionNav from './RunSectionNav'
import RunManifestPanel from './RunManifestPanel'
import { PipelineDisplayMeta } from '../utils/stageLabels'

interface Props {
  run: Run
  dbId: string
  wide?: boolean
  initialSection?: string
}

const RUN_SECTIONS = [
  { id: 'run-overview', label: 'Overview' },
  { id: 'architecture', label: 'Architecture' },
  { id: 'quality', label: 'Quality' },
  { id: 'tradeoffs', label: 'Tradeoffs' },
  { id: 'queries', label: 'Queries' },
] as const

function Section({ id, title, subtitle, children }: { id: string; title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="mb-8 scroll-mt-28">
      <div className="mb-3">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        {subtitle && <p className="text-xs text-ink-muted mt-0.5">{subtitle}</p>}
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

function inferLatencyBudget(metrics: MetricsMap): number {
  const latencies = Object.values(metrics)
    .filter((e) => e.metric_name === 'latency_p50' && e.stage_index < 0)
    .map((e) => e.mean)
  if (latencies.length === 0) return 2000
  const sorted = [...latencies].sort((a, b) => a - b)
  const inferred = Math.round(sorted[Math.floor(sorted.length * 0.75)] * 2)
  return Math.min(30000, Math.max(100, inferred))
}

export default function RunDetail({ run, dbId, wide = false, initialSection }: Props) {
  const [metrics, setMetrics] = useState<MetricsMap | null>(null)
  const [overview, setOverview] = useState<RunOverview | null>(null)
  const [baselines, setBaselines] = useState<Record<string, number>>({})
  const [error, setError] = useState<string | null>(null)
  const [latencyBudgetMs, setLatencyBudgetMs] = useState<number>(2000)
  const [minQualityDelta, setMinQualityDelta] = useState<number>(0.02)

  const datasetName = extractDatasetName(run)
  const displayMeta = useMemo(
    () => (overview?.manifest ?? null) as PipelineDisplayMeta | null,
    [overview],
  )

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
          setLatencyBudgetMs(ov.manifest.latency_budget_ms as number)
        }
      })
      .catch(() => setOverview(null))
  }, [dbId, run.run_id])

  useEffect(() => {
    if (initialSection) {
      requestAnimationFrame(() => {
        document.getElementById(initialSection)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      })
    }
  }, [initialSection, metrics])

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
      <div className="p-6 flex items-center gap-2 text-ink-faint text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 dark:border-slate-600 border-t-indigo-600" />
        Loading metrics...
      </div>
    )
  }

  const showTradeoffExplorer = pipelineCount >= 2
  const hasStageMetrics = Object.values(metrics).some((e) => e.stage_index >= 0)

  return (
    <div className={`p-6 ${wide ? 'max-w-full' : 'max-w-5xl'}`}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-ink">{run.experiment_name}</h1>
          <p className="text-sm text-ink-muted font-mono mt-0.5">{run.run_id}</p>
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

      <RunSectionNav sections={[...RUN_SECTIONS]} activeId={initialSection} />

      <Section id="run-overview" title="Run Overview" subtitle="Headline verdict, dataset manifest, and data-quality warnings">
        <DashboardGuide />
        <RunManifestPanel overview={overview} />
        {showTradeoffExplorer && (
          <div className="mb-4 p-4 border border-indigo-100 dark:border-indigo-900 rounded-lg bg-indigo-50/40 dark:bg-indigo-950/30">
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
      </Section>

      {hasStageMetrics && (
        <Section id="architecture" title="Pipeline Architecture" subtitle="Directed graph — parallel branches, merge points, per-node quality with bootstrap CIs">
          <PipelineDagView dbId={dbId} runId={run.run_id} />
        </Section>
      )}

      <Section id="quality" title="Quality" subtitle="Metrics summary, recall curves, stage funnel, and combination matrix">
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
      </Section>

      <Section id="tradeoffs" title="Tradeoffs" subtitle="End-to-end latency vs quality, and per-stage latency breakdown">
        <div className="space-y-8">
          <TradeoffScatter dbId={dbId} runId={run.run_id} latencyBudgetMs={latencyBudgetMs} />
          <div>
            <h3 className="text-sm font-semibold text-ink mb-2">Latency Breakdown</h3>
            <LatencyChart metrics={metrics} displayMeta={displayMeta} />
          </div>
        </div>
      </Section>

      <Section id="queries" title="Queries" subtitle="Per-query exploration, winners, attribution, and segment breakdowns">
        <div className="space-y-8">
          <QueryWinnerTable dbId={dbId} runId={run.run_id} />
          <QueryExplorer dbId={dbId} runId={run.run_id} />
          <SegmentOperatorGrid dbId={dbId} runId={run.run_id} />
          <OperatorInspector dbId={dbId} runId={run.run_id} />
          <SegmentBreakdown dbId={dbId} runId={run.run_id} field="n_relevant" targetMetric="ndcg" />
          <StressTestResults dbId={dbId} runId={run.run_id} />
        </div>
      </Section>
    </div>
  )
}
