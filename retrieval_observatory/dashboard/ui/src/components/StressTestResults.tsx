import { useEffect, useState } from 'react'
import { fetchSegmentMetrics } from '../api'
import SegmentBreakdown from './SegmentBreakdown'

interface Props {
  dbId: string
  runId: string
}

// Self-gating: renders the Test Sets stress-test breakdown ONLY when the run's queries
// carry Test Sets metadata (scenario_type / difficulty_label). Otherwise renders nothing,
// so non-Test Sets runs are unaffected. This keeps the section factual — it appears exactly
// when there is data to back it.
export default function StressTestResults({ dbId, runId }: Props) {
  const [hasScenario, setHasScenario] = useState(false)
  const [hasDifficulty, setHasDifficulty] = useState(false)
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      fetchSegmentMetrics(dbId, runId, 'scenario_type').catch(() => null),
      fetchSegmentMetrics(dbId, runId, 'difficulty_label').catch(() => null),
    ]).then(([sc, df]) => {
      if (cancelled) return
      setHasScenario(!!sc && Object.keys(sc.segments).length > 0)
      setHasDifficulty(!!df && Object.keys(df.segments).length > 0)
      setChecked(true)
    })
    return () => {
      cancelled = true
    }
  }, [dbId, runId])

  if (!checked || (!hasScenario && !hasDifficulty)) return null

  return (
    <section className="mb-8">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-amber-600">🜂</span>
        <h2 className="text-base font-semibold text-gray-800 dark:text-slate-100">Stress Test Results</h2>
        <span className="text-[10px] font-medium uppercase tracking-wide text-amber-700 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5">
          Test Set
        </span>
      </div>
      <p className="text-xs text-gray-400 dark:text-slate-500 mb-4">
        Performance broken down by the failure scenario and difficulty each query was generated to probe —
        this is where benchmark-blindness shows up (e.g. strong overall but weak on temporal queries).
      </p>

      {hasScenario && (
        <div className="mb-6">
          <p className="text-sm font-medium text-gray-700 dark:text-slate-200 mb-1">NDCG@10 by scenario type</p>
          <SegmentBreakdown dbId={dbId} runId={runId} field="scenario_type" targetMetric="ndcg" />
        </div>
      )}
      {hasDifficulty && (
        <div>
          <p className="text-sm font-medium text-gray-700 dark:text-slate-200 mb-1">NDCG@10 by difficulty</p>
          <SegmentBreakdown dbId={dbId} runId={runId} field="difficulty_label" targetMetric="ndcg" />
        </div>
      )}
    </section>
  )
}
