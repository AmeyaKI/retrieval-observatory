import { useEffect, useState } from 'react'
import DataQualityWarnings from './DataQualityWarnings'
import { fetchComparison, ComparisonEntry, RunSelection, selectionKey } from '../api'
import { formatMetricKey } from '../utils/formatMetricKey'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'

interface Props {
  selections: RunSelection[]
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
  if (isLoser) return 'px-3 py-2 text-right tabular-nums text-xs text-gray-400'
  return 'px-3 py-2 text-right tabular-nums text-xs'
}

function determineWinner(
  row: ComparisonEntry,
  runKeys: string[],
  isLatency: boolean,
): 'left' | 'right' | 'tie' | null {
  if (runKeys.length !== 2) return null
  const a = (row[runKeys[0]] as { mean: number | null } | undefined)?.mean
  const b = (row[runKeys[1]] as { mean: number | null } | undefined)?.mean
  if (a == null || b == null) return null
  const diff = Math.abs(a - b)
  if (diff < 1e-5) return 'tie'
  // For latency: lower is better; for quality: higher is better
  if (isLatency) return a < b ? 'left' : 'right'
  return a > b ? 'left' : 'right'
}

function SectionHeader({ title, note }: { title: string; note?: string }) {
  return (
    <tr className="bg-gray-100">
      <td colSpan={100} className="px-3 py-1.5 text-xs font-bold text-gray-600 uppercase tracking-wide">
        {title}
        {note && <span className="ml-2 font-normal normal-case text-gray-400">{note}</span>}
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
        : 'bg-gray-50 border-gray-200 text-gray-700'
    }`}>
      <span className="font-semibold">
        {overallWinner
          ? `Run ${overallWinner} wins overall`
          : 'Runs are roughly equivalent'}
      </span>
      <span className="ml-2 text-xs opacity-75">
        (A better on {aWins} metrics · B better on {bWins} metrics)
      </span>
    </div>
  )
}

export default function ComparePanel({ selections }: Props) {
  const [comparison, setComparison] = useState<ComparisonEntry[] | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  const runKeys = selections.map((s) => `${s.dbId}/${s.runId}`)

  useEffect(() => {
    setComparison(null)
    setWarnings([])
    setError(null)
    fetchComparison(selections)
      .then((data) => {
        setComparison(data.comparison)
        setWarnings(data.warnings ?? [])
      })
      .catch((e) => setError(e.message))
  }, [selections.map(selectionKey).join(',')])

  if (error) {
    return (
      <div className="p-6">
        <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
      </div>
    )
  }

  if (!comparison) {
    return (
      <div className="p-6 flex items-center gap-2 text-gray-400 text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 border-t-indigo-600" />
        Loading comparison...
      </div>
    )
  }

  const twoRuns = runKeys.length === 2

  // Group rows by category
  const qualityRows = comparison.filter((r) => metricCategory(r.metric) === 'quality')
  const latencyRows = comparison.filter((r) => metricCategory(r.metric) === 'latency')
  const otherRows = comparison.filter((r) => metricCategory(r.metric) === 'other')

  const renderRows = (rows: ComparisonEntry[], isLatency: boolean) =>
    rows.map((row) => {
      const winner = twoRuns ? determineWinner(row, runKeys, isLatency) : null
      const pv = row.p_value as number | undefined
      const significant = pv !== undefined && pv < 0.05
      return (
        <tr key={row.metric} className="hover:bg-gray-50 border-b border-gray-100">
          <td className="px-3 py-2 text-xs text-gray-800">
            {formatMetricKey(row.metric)}
            {twoRuns && <WinBadge winner={winner} />}
          </td>
          {runKeys.map((key, i) => {
            const v = row[key] as { mean: number | null; std: number | null } | undefined
            const isWinner = twoRuns && winner === (i === 0 ? 'left' : 'right')
            const isLoser = twoRuns && winner !== null && winner !== 'tie' && !isWinner
            return (
              <td key={key} className={cellClass(isWinner, isLoser)}>
                {v?.mean != null ? (
                  <>
                    <span>{fmt(v.mean, isLatency ? 1 : 4)}</span>
                    {v.std != null && (
                      <span className="text-gray-400 ml-1">±{fmt(v.std, isLatency ? 1 : 4)}</span>
                    )}
                    {isWinner && <span className="ml-1 text-green-600">▲</span>}
                  </>
                ) : '—'}
              </td>
            )
          })}
          <td className={`px-3 py-2 text-right tabular-nums text-xs ${significant ? 'font-bold text-indigo-700' : 'text-gray-400'}`}>
            {pv !== undefined ? `${pv.toFixed(3)}${significant ? ' *' : ''}` : '—'}
          </td>
        </tr>
      )
    })

  // Short run labels (last part of db/runId)
  const runLabels = runKeys.map((k, i) => {
    const parts = k.split('/')
    return { label: `Run ${String.fromCharCode(65 + i)}: ${parts[parts.length - 1]}`, full: k }
  })

  return (
    <div className="p-6 max-w-6xl">
      <h1 className="text-xl font-bold text-gray-900 mb-1">Run Comparison</h1>
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

      {twoRuns && <SummaryBanner comparison={comparison} runKeys={runKeys} />}

      <DataQualityWarnings warnings={warnings} />

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="bg-gray-100 text-left border-b border-gray-200">
              <th className="px-3 py-2 font-semibold text-gray-700">Metric</th>
              {runLabels.map((r, i) => (
                <th
                  key={r.full}
                  className={`px-3 py-2 font-semibold text-right text-xs ${
                    i === 0 ? 'text-green-700' : 'text-blue-700'
                  }`}
                >
                  {`Run ${String.fromCharCode(65 + i)}`}
                  <span className="block font-normal font-mono text-gray-400">{r.full}</span>
                </th>
              ))}
              <th className="px-3 py-2 font-semibold text-gray-700 text-right">
                p-value
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
        <p className="text-xs text-gray-400">
          * p &lt; 0.05 (paired bootstrap significance test on matched query IDs)
        </p>
        <p className="text-xs text-gray-400">
          Green cells = winner on that metric. Win counts in summary banner include all metrics regardless of significance.
        </p>
        {!twoRuns && (
          <p className="text-xs text-amber-600">
            Win highlighting is only shown when exactly 2 runs are compared.
          </p>
        )}
      </div>
    </div>
  )
}
