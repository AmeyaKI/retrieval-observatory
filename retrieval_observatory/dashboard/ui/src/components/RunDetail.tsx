import { useEffect, useState } from 'react'
import { fetchMetrics, fetchBaselines, MetricsMap, Run } from '../api'
import MetricsTable from './MetricsTable'
import RecallCurve from './RecallCurve'
import RecallFunnel from './RecallFunnel'
import LatencyChart from './LatencyChart'
import SegmentBreakdown from './SegmentBreakdown'

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

export default function RunDetail({ run }: Props) {
  const [metrics, setMetrics] = useState<MetricsMap | null>(null)
  const [baselines, setBaselines] = useState<Record<string, number>>({})
  const [error, setError] = useState<string | null>(null)

  const datasetName = extractDatasetName(run)

  useEffect(() => {
    setMetrics(null)
    setError(null)
    fetchMetrics(run.run_id)
      .then(setMetrics)
      .catch((e) => setError(e.message))
  }, [run.run_id])

  useEffect(() => {
    if (datasetName) {
      fetchBaselines(datasetName)
        .then(setBaselines)
        .catch(() => setBaselines({}))
    }
  }, [datasetName])

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

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">{run.experiment_name}</h1>
          <p className="text-sm text-gray-500 font-mono mt-0.5">{run.run_id}</p>
        </div>
      </div>

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

      <Section title="NDCG@10 by Number of Relevant Docs">
        <SegmentBreakdown runId={run.run_id} field="n_relevant" targetMetric="ndcg" />
      </Section>
    </div>
  )
}
