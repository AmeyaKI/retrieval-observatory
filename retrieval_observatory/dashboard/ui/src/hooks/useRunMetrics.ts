import { useEffect, useState } from 'react'
import { fetchBaselines, fetchMetrics, fetchRunOverview, MetricsMap, RunOverview } from '../api'

function extractDatasetName(configJson: string): string {
  try {
    const cfg = JSON.parse(configJson)
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

/** Shared metrics/overview/baselines fetch for every routed run page (Item B). Each page
 * mounts independently (real routes un-mount inactive pages, unlike the old single-scroll
 * layout), so this hook is called per-page rather than fetched once and threaded through
 * props -- simpler, and no worse than before since only one page is ever mounted at a time. */
export function useRunMetrics(dbId: string, runId: string, configJson: string) {
  const [metrics, setMetrics] = useState<MetricsMap | null>(null)
  const [overview, setOverview] = useState<RunOverview | null>(null)
  const [baselines, setBaselines] = useState<Record<string, number>>({})
  const [error, setError] = useState<string | null>(null)
  const [latencyBudgetMs, setLatencyBudgetMs] = useState<number>(2000)

  useEffect(() => {
    setMetrics(null)
    setOverview(null)
    setError(null)
    fetchMetrics(dbId, runId)
      .then((m) => {
        setMetrics(m)
        setLatencyBudgetMs(inferLatencyBudget(m))
      })
      .catch((e) => setError(e.message))
    fetchRunOverview(dbId, runId)
      .then((ov) => {
        setOverview(ov)
        if (typeof ov.manifest?.latency_budget_ms === 'number') {
          setLatencyBudgetMs(ov.manifest.latency_budget_ms as number)
        }
      })
      .catch(() => setOverview(null))
  }, [dbId, runId])

  useEffect(() => {
    const datasetName = extractDatasetName(configJson)
    if (datasetName) {
      fetchBaselines(datasetName)
        .then(setBaselines)
        .catch(() => setBaselines({}))
    }
  }, [configJson])

  return { metrics, overview, baselines, error, latencyBudgetMs, setLatencyBudgetMs }
}
