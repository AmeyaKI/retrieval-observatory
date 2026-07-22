import { ReleaseDecision, ReleaseGuardResult } from '../api'
import ReleaseEvidenceMatrix from './ReleaseEvidenceMatrix'
import ReleaseSliceTable from './ReleaseSliceTable'

function fmt(value: number | null): string {
  return value == null ? '—' : value.toFixed(4)
}

function statusClass(status: ReleaseDecision['status']): string {
  if (status === 'PASS') return 'border-emerald-400 bg-emerald-50 dark:bg-emerald-950/20'
  if (status === 'HOLD') return 'border-amber-400 bg-amber-50 dark:bg-amber-950/20'
  return 'border-red-400 bg-red-50 dark:bg-red-950/20'
}

function GuardRows({ guards, onSelect, canNavigate }: { guards: ReleaseGuardResult[]; onSelect: (metric: string) => void; canNavigate: boolean }) {
  if (guards.length === 0) return <p className="text-xs text-ink-muted">No policy guards were evaluated.</p>
  return <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
    <table className="min-w-full text-xs">
      <thead className="bg-surface-muted text-left text-ink-faint"><tr>
        <th className="p-2">Metric</th><th className="p-2">Status</th><th className="p-2">Paired interval</th><th className="p-2">Budget</th><th className="p-2">Paired n</th>
      </tr></thead>
      <tbody>{guards.map(guard => {
        const actionable = ['HOLD', 'BLOCK', 'FAIL'].includes(guard.status)
        return <tr key={guard.metric} className="border-t border-slate-200 dark:border-slate-700">
          <td className="p-2 font-mono">{actionable && canNavigate ? <button type="button" onClick={() => onSelect(guard.metric)} className="text-left underline">{guard.metric}</button> : guard.metric}</td>
          <td className="p-2 font-semibold">{guard.status}</td>
          <td className="p-2 font-mono">[{fmt(guard.ci_low)}, {fmt(guard.ci_high)}]</td>
          <td className="p-2 font-mono">{guard.direction === 'higher_is_better' ? '≥ -' : '≤ '}{guard.max_regression}</td>
          <td className="p-2 font-mono">{guard.paired_n}/{guard.min_paired_n}</td>
        </tr>
      })}</tbody>
    </table>
  </div>
}

export default function ReleaseDecisionCard({
  decision,
  onQueryMetricSelect,
}: {
  decision: ReleaseDecision
  onQueryMetricSelect: (metric: string, queryId: string) => void
}) {
  const affectedQuery = decision.investigation.affected_query_ids[0]
  const selectGuard = (metric: string) => {
    if (affectedQuery) onQueryMetricSelect(metric, affectedQuery)
  }
  return (
    <section aria-labelledby="release-decision-heading" className={`mb-4 rounded-lg border-l-4 p-4 space-y-4 ${statusClass(decision.status)}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-ink-muted">Release decision</p>
          <h2 id="release-decision-heading" className="text-2xl font-bold text-ink">{decision.status}</h2>
          <ul className="mt-1 list-disc pl-4 text-xs text-ink-muted">{decision.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
        </div>
        <dl className="text-xs">
          <div><dt className="inline text-ink-faint">Policy: </dt><dd className="inline font-mono">{decision.policy.configured ? decision.policy.id ?? 'configured' : 'not configured'}</dd></div>
          <div><dt className="inline text-ink-faint">Digest: </dt><dd className="inline font-mono">{decision.policy.digest ?? '—'}</dd></div>
          <div><dt className="inline text-ink-faint">Schema: </dt><dd className="inline font-mono">{decision.schema_version}</dd></div>
        </dl>
      </div>
      <ReleaseEvidenceMatrix readiness={decision.readiness} />
      <section aria-labelledby="paired-intervals-heading" className="space-y-2">
        <h3 id="paired-intervals-heading" className="text-sm font-semibold text-ink">Paired policy intervals</h3>
        <GuardRows guards={decision.aggregate_guards} onSelect={selectGuard} canNavigate={Boolean(affectedQuery)} />
      </section>
      <ReleaseSliceTable slices={decision.slices} onGuardSelect={selectGuard} canNavigate={Boolean(affectedQuery)} />
      <p className="text-xs"><span className="font-semibold">Next action:</span> {decision.next_action}</p>
      {!affectedQuery && decision.aggregate_guards.some(guard => ['HOLD', 'BLOCK', 'FAIL'].includes(guard.status)) ? (
        <p className="text-xs text-ink-muted">No affected query reference is available for these guards.</p>
      ) : null}
    </section>
  )
}
