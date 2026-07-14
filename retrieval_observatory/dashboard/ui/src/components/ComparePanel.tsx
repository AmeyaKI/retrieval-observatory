import { useEffect, useState } from 'react'
import DataQualityWarnings from './DataQualityWarnings'
import { fetchComparison, ComparabilityReport, ComparisonEntry, QueryDiffs, RunSelection, selectionKey } from '../api'
import { formatMetricKey } from '../utils/formatMetricKey'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'
import RunComparisonDeepDiffs from './RunComparisonDeepDiffs'
import StatusPanel from './StatusPanel'

interface Props {
  selections: RunSelection[]
}

/**
 * Comparability guard (Pillar 6): make it hard to accidentally compare incomparable
 * experiments. Surfaces exactly what differs (dataset content, seed, git commit, package
 * versions) before any metrics and blocks decision-bearing labels when invalid.
 */
function ComparabilityBanner({ report }: { report: ComparabilityReport }) {
  if (report.differences.length === 0) return null
  const blocking = !report.decision_allowed
  const details = (
      <ul className="list-disc pl-5 space-y-0.5">
        {report.differences.map((d, i) => (
          <li key={i}>
            <span className="font-mono text-xs uppercase mr-1">{d.axis}</span>
            {d.detail}
          </li>
        ))}
      </ul>
  )
  return <div className="mb-3"><StatusPanel kind={blocking ? 'invalid' : 'partial'} title={blocking ? 'No comparison decision — validity requirements failed' : 'Comparability notes'} message={details} /></div>
}

function fmt(v: number | null | undefined, decimals = 4): string {
  if (v == null) return '—'
  return v.toFixed(decimals)
}

function isQualityMetric(metric: string): boolean {
  return /ndcg|recall|mrr|map|precision/i.test(metric)
}

function isLatencyMetric(metric: string): boolean {
  return /latency/i.test(metric)
}

function metricCategory(metric: string): 'quality' | 'latency' | 'other' {
  if (isQualityMetric(metric)) return 'quality'
  if (isLatencyMetric(metric)) return 'latency'
  return 'other'
}

function WinBadge({ winner }: { winner: 'left' | 'right' | 'tie' | null }) {
  if (!winner || winner === 'tie') return null
  return (
    <span className={`inline-block ml-1.5 text-[10px] font-bold px-1 py-0.5 rounded ${
      winner === 'left'
        ? 'bg-green-100 text-green-700'
        : 'bg-blue-100 text-blue-700'
    }`}>
      {winner === 'left' ? 'A wins' : 'B wins'}
    </span>
  )
}

function cellClass(isWinner: boolean, isLoser: boolean): string {
  if (isWinner) return 'px-3 py-2 text-right tabular-nums text-xs bg-green-50 font-semibold text-green-800'
  if (isLoser) return 'px-3 py-2 text-right tabular-nums text-xs text-gray-400 dark:text-slate-500'
  return 'px-3 py-2 text-right tabular-nums text-xs'
}

function determineWinner(
  row: ComparisonEntry,
  runKeys: string[],
  _isLatency: boolean,
): 'left' | 'right' | 'tie' | null {
  if (runKeys.length !== 2) return null
  if (row.statistics?.decision === 'candidate_better') return 'right'
  if (row.statistics?.decision === 'candidate_worse') return 'left'
  return null
}

function SectionHeader({ title, note }: { title: string; note?: string }) {
  return (
    <tr className="bg-gray-100 dark:bg-slate-800">
      <td colSpan={100} className="px-3 py-1.5 text-xs font-bold text-gray-600 dark:text-slate-300 uppercase tracking-wide">
        {title}
        {note && <span className="ml-2 font-normal normal-case text-gray-400 dark:text-slate-500">{note}</span>}
      </td>
    </tr>
  )
}

function SummaryBanner({
  comparison,
  runKeys,
}: {
  comparison: ComparisonEntry[]
  runKeys: string[]
}) {
  if (runKeys.length !== 2) return null

  let aWins = 0
  let bWins = 0
  for (const row of comparison) {
    const isLatency = isLatencyMetric(row.metric)
    const winner = determineWinner(row, runKeys, isLatency)
    if (winner === 'left') aWins++
    else if (winner === 'right') bWins++
  }

  const total = aWins + bWins
  if (total === 0) return null

  const overallWinner = aWins > bWins ? 'A' : bWins > aWins ? 'B' : null

  return (
    <div className={`mb-4 p-3 rounded-lg border text-sm ${
      overallWinner === 'A'
        ? 'bg-green-50 border-green-200 text-green-800'
        : overallWinner === 'B'
        ? 'bg-blue-50 border-blue-200 text-blue-800'
        : 'bg-gray-50 dark:bg-slate-800/60 border-gray-200 dark:border-slate-700 text-gray-700 dark:text-slate-200'
    }`}>
      <span className="font-semibold">
        {overallWinner
        ? `${overallWinner === 'B' ? 'Candidate improves' : 'Candidate regresses'} on the decision-bearing metrics`
          : 'No decision-bearing metric difference'}
      </span>
      <span className="ml-2 text-xs opacity-75">
        (baseline better on {aWins} · candidate better on {bWins}; BH-corrected and effect-thresholded)
      </span>
    </div>
  )
}

export default function ComparePanel({ selections }: Props) {
  const [comparison, setComparison] = useState<ComparisonEntry[] | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [comparability, setComparability] = useState<ComparabilityReport | null>(null)
  const [queryDiffs, setQueryDiffs] = useState<QueryDiffs | null>(null)
  const [error, setError] = useState<string | null>(null)

  const runKeys = selections.map((s) => `${s.dbId}/${s.runId}`)

  useEffect(() => {
    setComparison(null)
    setWarnings([])
    setComparability(null)
    setQueryDiffs(null)
    setError(null)
    fetchComparison(selections)
      .then((data) => {
        setComparison(data.comparison)
        setWarnings(data.warnings ?? [])
        setComparability(data.comparability ?? null)
        setQueryDiffs(data.query_diffs ?? null)
      })
      .catch((e) => setError(e.message))
  }, [selections.map(selectionKey).join(',')])

  if (error) {
    return <div className="p-6"><StatusPanel kind="error" title="Comparison could not be loaded" message={error} /></div>
  }

  if (!comparison) {
    return <div className="p-6"><StatusPanel kind="loading" message="Loading baseline and candidate evidence…" /></div>
  }

  if (comparison.length === 0) {
    return <div className="p-6"><StatusPanel kind="empty" title="No comparable measurements" message="The selected runs have no shared metrics." /></div>
  }

  const twoRuns = runKeys.length === 2

  // Group rows by category
  const qualityRows = comparison.filter((r) => metricCategory(r.metric) === 'quality')
  const latencyRows = comparison.filter((r) => metricCategory(r.metric) === 'latency')
  const otherRows = comparison.filter((r) => metricCategory(r.metric) === 'other')

  const renderRows = (rows: ComparisonEntry[], isLatency: boolean) =>
    rows.map((row) => {
      const winner = twoRuns ? determineWinner(row, runKeys, isLatency) : null
      const qv = row.q_value as number | null | undefined
      const significant = row.statistics?.significant === true && !row.statistics.low_power
      return (
        <tr key={row.metric} className="hover:bg-gray-50 border-b border-gray-100 dark:border-slate-800">
          <td className="px-3 py-2 text-xs text-gray-800 dark:text-slate-100">
            {formatMetricKey(row.metric)}
            {twoRuns && <WinBadge winner={winner} />}
            {twoRuns && row.statistics?.decision === 'no_decision' && (
              <span className="ml-1.5 text-[10px] text-gray-500" title={row.statistics.reason}>no decision</span>
            )}
          </td>
          {runKeys.map((key, i) => {
            const v = row[key] as { mean: number | null; std: number | null; ci_low?: number | null; ci_high?: number | null } | undefined
            const isWinner = twoRuns && winner === (i === 0 ? 'left' : 'right')
            const isLoser = twoRuns && winner !== null && winner !== 'tie' && !isWinner
            const showCi = !isLatency && v?.ci_low != null && v?.ci_high != null
            return (
              <td key={key} className={cellClass(isWinner, isLoser)}>
                {v?.mean != null ? (
                  <>
                    <span>{fmt(v.mean, isLatency ? 1 : 4)}</span>
                    {showCi ? (
                      <span className="block text-[9px] text-gray-400 dark:text-slate-500">
                        [{fmt(v.ci_low!, isLatency ? 1 : 4)}, {fmt(v.ci_high!, isLatency ? 1 : 4)}]
                      </span>
                    ) : v.std != null ? (
                      <span className="text-gray-400 dark:text-slate-500 ml-1">±{fmt(v.std, isLatency ? 1 : 4)}</span>
                    ) : null}
                    {isWinner && <span className="ml-1 text-green-600">▲</span>}
                  </>
                ) : '—'}
              </td>
            )
          })}
          <td className={`px-3 py-2 text-right tabular-nums text-xs ${significant ? 'font-bold text-indigo-700' : 'text-gray-400 dark:text-slate-500'}`}>
            {qv != null ? `${qv.toFixed(3)}${significant ? ' *' : ''}` : '—'}
          </td>
        </tr>
      )
    })

  // Short run labels (last part of db/runId)
  const runLabels = runKeys.map((k, i) => {
    const parts = k.split('/')
    return { label: `${i === 0 ? 'Baseline' : i === 1 ? 'Candidate' : `Reference ${i - 1}`}: ${parts[parts.length - 1]}`, full: k }
  })

  return (
    <div className="p-6 max-w-6xl">
      <h1 className="text-xl font-bold text-gray-900 dark:text-slate-100 mb-1">Run Comparison</h1>
      <div className="flex flex-wrap gap-2 mb-3">
        {runLabels.map((r, i) => (
          <span
            key={r.full}
            className={`text-xs px-2 py-1 rounded font-medium border ${
              i === 0 ? 'bg-green-50 border-green-200 text-green-800' : 'bg-blue-50 border-blue-200 text-blue-800'
            }`}
          >
            {r.label}
          </span>
        ))}
      </div>

      {comparability && <ComparabilityBanner report={comparability} />}

      {twoRuns && <SummaryBanner comparison={comparison} runKeys={runKeys} />}

      <DataQualityWarnings warnings={warnings} />

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="bg-gray-100 dark:bg-slate-800 text-left border-b border-gray-200 dark:border-slate-700">
              <th className="px-3 py-2 font-semibold text-gray-700 dark:text-slate-200">Metric</th>
              {runLabels.map((r, i) => (
                <th
                  key={r.full}
                  className={`px-3 py-2 font-semibold text-right text-xs ${
                    i === 0 ? 'text-green-700' : 'text-blue-700'
                  }`}
                >
                  {i === 0 ? 'Baseline' : i === 1 ? 'Candidate' : `Reference ${i - 1}`}
                  <span className="block font-normal font-mono text-gray-400 dark:text-slate-500">{r.full}</span>
                </th>
              ))}
              <th className="px-3 py-2 font-semibold text-gray-700 dark:text-slate-200 text-right">
                q-value
                <MetricTooltip text={METRIC_GLOSSARY.p_value} alignLeft />
              </th>
            </tr>
          </thead>
          <tbody>
            {qualityRows.length > 0 && (
              <>
                <SectionHeader title="Quality Metrics" note="higher is better" />
                {renderRows(qualityRows, false)}
              </>
            )}
            {latencyRows.length > 0 && (
              <>
                <SectionHeader title="Latency" note="lower is better" />
                {renderRows(latencyRows, true)}
              </>
            )}
            {otherRows.length > 0 && (
              <>
                <SectionHeader title="Other" />
                {renderRows(otherRows, false)}
              </>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-3 space-y-1">
        <p className="text-xs text-gray-400 dark:text-slate-500">
          * q &lt; 0.05 after Benjamini–Hochberg correction, paired n ≥ 20, and the declared practical effect threshold is exceeded.
        </p>
        <p className="text-xs text-gray-400 dark:text-slate-500">
          Winner labels appear only for valid, adequately powered, statistically significant, practically meaningful paired effects.
        </p>
        {!twoRuns && (
          <p className="text-xs text-amber-600">
            Win highlighting is only shown when exactly 2 runs are compared.
          </p>
        )}
      </div>

      {twoRuns && <RunComparisonDeepDiffs selections={selections} queryDiffs={queryDiffs} />}
    </div>
  )
}
