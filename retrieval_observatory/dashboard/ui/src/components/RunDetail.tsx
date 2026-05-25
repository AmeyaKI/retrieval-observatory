import { useEffect, useState } from 'react'
import { fetchMetrics, MetricsMap } from '../api'
import MetricsTable from './MetricsTable'
import RecallCurve from './RecallCurve'
import RecallFunnel from './RecallFunnel'
import LatencyChart from './LatencyChart'

interface Props {
  runId: string
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="text-base font-semibold text-gray-800 mb-3">{title}</h2>
      {children}
    </section>
  )
}

export default function RunDetail({ runId }: Props) {
  const [metrics, setMetrics] = useState<MetricsMap | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setMetrics(null)
    setError(null)
    fetchMetrics(runId)
      .then(setMetrics)
      .catch((e) => setError(e.message))
  }, [runId])

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
          <h1 className="text-xl font-bold text-gray-900">Run Detail</h1>
          <p className="text-sm text-gray-500 font-mono mt-0.5">{runId}</p>
        </div>
      </div>

      <Section title="Metrics Summary">
        <MetricsTable metrics={metrics} />
      </Section>

      <Section title="Recall@K Curves">
        <RecallCurve metrics={metrics} />
      </Section>

      <Section title="Stage Recall Funnel">
        <RecallFunnel metrics={metrics} />
      </Section>

      <Section title="Latency Percentiles">
        <LatencyChart metrics={metrics} />
      </Section>
    </div>
  )
}
