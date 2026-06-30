import { useEffect, useState } from 'react'
import { fetchRunOverview, RunOverview as Overview } from '../api'
import { formatMetricKey } from '../utils/formatMetricKey'
import { METRIC_GLOSSARY, lookupFailureLabel } from '../utils/metricGlossary'
import { MetricTooltip } from './MetricTooltip'
import ClassifierCalibration from './ClassifierCalibration'
import NoData from './NoData'

export default function ExperimentOverview({ dbId, runId }: { dbId: string; runId: string }) {
  const [overview, setOverview] = useState<Overview | null>(null)

  useEffect(() => {
    setOverview(null)
    fetchRunOverview(dbId, runId).then(setOverview).catch(() => setOverview(null))
  }, [dbId, runId])

  if (!overview) return <NoData label="No run overview data available." />

  const buckets = Object.entries(overview.diagnostics.difficulty_buckets || {})
  const labels = Object.entries(overview.diagnostics.failure_labels || {})
  const byPipeline = overview.diagnostics.by_pipeline ?? {}
  const pipelineEntries = Object.entries(byPipeline)

  const BUCKET_ORDER = ['easy', 'medium', 'hard', 'discriminative', 'unstable', 'unknown']
  const BUCKET_COLORS: Record<string, string> = {
    easy: 'bg-green-100 text-green-700',
    medium: 'bg-blue-100 text-blue-700',
    hard: 'bg-red-100 text-red-700',
    discriminative: 'bg-purple-100 text-purple-700',
    unstable: 'bg-amber-100 text-amber-700',
    unknown: 'bg-gray-100 text-gray-500',
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      <div className="border border-gray-200 rounded p-3 bg-white">
        <div className="text-xs uppercase tracking-wide text-gray-500">Headline</div>
        <div className="mt-1 text-sm font-semibold text-gray-900">
          {overview.headline_winner ? formatMetricKey(overview.headline_winner.metric) : 'No winner yet'}
        </div>
        {overview.headline_winner?.mean != null && (
          <div className="text-2xl font-bold tabular-nums mt-1">{overview.headline_winner.mean.toFixed(4)}</div>
        )}
      </div>
      <div className="border border-gray-200 rounded p-3 bg-white">
        <div className="text-xs uppercase tracking-wide text-gray-500">
          Diagnostic Buckets (post-hoc, from observed recall/variance)
          <MetricTooltip text={METRIC_GLOSSARY.difficulty_diagnostic} />
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {buckets.length ? BUCKET_ORDER.filter((b) => overview.diagnostics.difficulty_buckets[b]).map((name) => (
            <span key={name} className={`text-xs px-2 py-0.5 rounded font-medium ${BUCKET_COLORS[name] ?? 'bg-gray-100 text-gray-700'}`}>
              {name}: {overview.diagnostics.difficulty_buckets[name]}
            </span>
          )) : <span className="text-xs text-gray-400">No diagnostics</span>}
        </div>
      </div>
      <div className="border border-gray-200 rounded p-3 bg-white">
        <div className="text-xs uppercase tracking-wide text-gray-500 flex items-center gap-1">
          Failure Labels
          <MetricTooltip text={METRIC_GLOSSARY.failure_labels_intro} />
        </div>
        <p className="text-[10px] text-gray-400 mt-1 mb-2">Per query×pipeline — explains why retrieval failed, not aggregate scores.</p>
        <div className="mt-1 flex flex-wrap gap-2">
          {labels.length ? labels.map(([name, count]) => (
            <span
              key={name}
              className="text-xs px-2 py-1 rounded bg-red-50 text-red-700 cursor-help"
              title={lookupFailureLabel(name) ?? name}
            >
              {name}: {count}
            </span>
          )) : <span className="text-xs text-gray-400">No labeled failures</span>}
        </div>
      </div>

      {pipelineEntries.length > 1 && (
        <div className="md:col-span-3 border border-gray-200 rounded p-3 bg-white">
          <div className="text-xs uppercase tracking-wide text-gray-500 mb-2">Difficulty by Pipeline</div>
          <div className="space-y-1.5">
            {pipelineEntries.map(([pid, data]) => (
              <div key={pid} className="flex items-center gap-2 text-xs">
                <span className="text-gray-600 font-medium w-40 truncate" title={pid}>
                  {pid.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                </span>
                <div className="flex flex-wrap gap-1">
                  {BUCKET_ORDER.filter((b) => data.difficulty_buckets[b]).map((b) => (
                    <span key={b} className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${BUCKET_COLORS[b] ?? 'bg-gray-100 text-gray-700'}`}>
                      {b}: {data.difficulty_buckets[b]}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <ClassifierCalibration dbId={dbId} runId={runId} />
    </div>
  )
}
