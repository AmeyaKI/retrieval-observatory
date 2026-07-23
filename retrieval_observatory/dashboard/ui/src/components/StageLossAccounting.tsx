import { OutcomeCounts, StageLossAccounting as Accounting } from '../api'

const OUTCOMES: Array<[keyof OutcomeCounts, string]> = [
  ['relevant_retained', 'Relevant retained'], ['relevant_dropped_at_stage', 'Relevant dropped at stage'],
  ['relevant_lost_upstream', 'Relevant lost upstream'], ['irrelevant_retained', 'Irrelevant retained'],
  ['irrelevant_removed', 'Irrelevant removed'], ['unknown_relevance', 'Unknown relevance'], ['lineage_incomplete', 'Incomplete lineage'],
]

export default function StageLossAccounting({ accounting }: { accounting: Accounting }) {
  const recordedLoss = Object.entries(accounting.by_operator)
    .filter(([, counts]) => counts.relevant_dropped_at_stage > 0)
    .sort((left, right) => right[1].relevant_dropped_at_stage - left[1].relevant_dropped_at_stage)[0]
  return <section aria-labelledby="stage-loss-heading" className="space-y-2">
    <div><h3 id="stage-loss-heading" className="text-sm font-semibold">Stage loss accounting</h3><p className="text-xs text-ink-muted">Recorded counts by operator. These counts identify investigation points; they do not establish causality.</p></div>
    <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700" tabIndex={0}><table className="min-w-full text-xs">
      <thead className="bg-surface-muted text-left text-ink-faint"><tr><th className="p-2">Operator</th>{OUTCOMES.map(([, label]) => <th key={label} className="p-2">{label}</th>)}</tr></thead>
      <tbody>{Object.entries(accounting.by_operator).map(([operator, counts]) => <tr key={operator} className="border-t border-slate-200 dark:border-slate-700"><td className="p-2 font-mono">{operator}</td>{OUTCOMES.map(([key]) => <td key={key} className="p-2 font-mono">{counts[key] ?? 0}</td>)}</tr>)}</tbody>
    </table></div>
    {recordedLoss ? <p className="text-xs text-ink-muted">Recorded counts support inspecting <span className="font-mono">{recordedLoss[0]}</span> first: {recordedLoss[1].relevant_dropped_at_stage} relevant candidate{recordedLoss[1].relevant_dropped_at_stage === 1 ? '' : 's'} had an observed stage exit there. This is an investigation pointer, not a causal claim.</p> : null}
    {accounting.unknown_relevance_count > 0 || accounting.incomplete_lineage_count > 0 ? <p className="text-xs text-amber-800 dark:text-amber-200">Evidence limits: {accounting.unknown_relevance_count} unknown relevance; {accounting.incomplete_lineage_count} incomplete lineage.</p> : null}
  </section>
}
