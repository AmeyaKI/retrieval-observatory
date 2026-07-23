import { useMemo, useState } from 'react'
import { CandidateJourneyRow, CandidateOutcomeKind } from '../api'

const OUTCOME_META: Record<CandidateOutcomeKind, { label: string; className: string }> = {
  relevant_retained: { label: 'Relevant retained', className: 'bg-emerald-100 text-emerald-900 border-emerald-600' },
  irrelevant_removed: { label: 'Irrelevant removed', className: 'bg-blue-100 text-blue-900 border-blue-600' },
  irrelevant_retained: { label: 'Irrelevant retained', className: 'bg-amber-100 text-amber-950 border-amber-700' },
  relevant_lost_upstream: { label: 'Relevant lost upstream', className: 'bg-red-100 text-red-950 border-red-700' },
  relevant_dropped_at_stage: { label: 'Relevant dropped at stage', className: 'bg-red-100 text-red-950 border-red-700' },
  unknown_relevance: { label: 'Unknown relevance', className: 'bg-slate-100 text-slate-800 border-slate-500' },
  lineage_incomplete: { label: 'Lineage incomplete', className: 'bg-violet-100 text-violet-900 border-violet-600' },
}

function outcomeFor(row: CandidateJourneyRow): CandidateOutcomeKind {
  return row.outcome ?? 'lineage_incomplete'
}

export default function CandidateMissTable({
  rows,
  queryText,
  selectedDocId,
  onSelect,
}: {
  rows: CandidateJourneyRow[]
  queryText?: string | null
  selectedDocId: string | null
  onSelect: (docId: string, pipelineId: string, traceId: string) => void
}) {
  const [filter, setFilter] = useState<'all' | CandidateOutcomeKind>('all')
  const counts = useMemo(() => rows.reduce<Record<string, number>>((result, row) => {
    const outcome = outcomeFor(row); result[outcome] = (result[outcome] ?? 0) + 1; return result
  }, {}), [rows])
  const filtered = filter === 'all' ? rows : rows.filter(row => outcomeFor(row) === filter)
  const presentOutcomes = (Object.keys(OUTCOME_META) as CandidateOutcomeKind[]).filter(outcome => counts[outcome])

  return <section className="space-y-2" id="candidate-outcome-table" aria-labelledby="candidate-outcome-heading">
    <div><h3 id="candidate-outcome-heading" className="text-sm font-semibold text-ink">Candidate outcomes</h3><p className="text-xs text-ink-muted mt-0.5">Observed candidates for this query{queryText ? <>: <span className="italic text-ink">{queryText}</span></> : null}. Select a row to inspect its trace-qualified passport.</p></div>
    <div className="flex flex-wrap gap-1.5">
      <button type="button" onClick={() => setFilter('all')} className={`rounded border px-2 py-1 text-[11px] ${filter === 'all' ? 'border-indigo-400 bg-indigo-50 text-indigo-800' : 'border-slate-200 text-ink-muted'}`}>All ({rows.length})</button>
      {presentOutcomes.map(outcome => <button key={outcome} type="button" onClick={() => setFilter(outcome)} className={`rounded border px-2 py-1 text-[11px] ${OUTCOME_META[outcome].className} ${filter === outcome ? 'ring-2 ring-indigo-500' : ''}`}>{OUTCOME_META[outcome].label} · {counts[outcome]}</button>)}
    </div>
    {filtered.length === 0 ? <p className="rounded border border-dashed p-3 text-xs text-ink-faint">No candidates match this filter.</p> : <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700" tabIndex={0}><table className="w-full min-w-[760px] text-left text-xs">
      <thead className="bg-surface-muted text-ink-faint"><tr><th className="p-2">Outcome</th><th className="p-2">Chunk preview</th><th className="p-2">Pipeline</th><th className="p-2">Evidence</th><th className="p-2">Removed at</th><th className="p-2">Reason</th><th className="p-2">Rank</th><th className="p-2">Candidate ID</th></tr></thead>
      <tbody>{filtered.map(row => {
        const outcome = outcomeFor(row); const meta = OUTCOME_META[outcome]; const selected = selectedDocId === row.doc_id
        return <tr key={`${row.trace_id}:${row.pipeline_id}:${row.doc_id}`} className={`border-t border-slate-200 dark:border-slate-700 cursor-pointer ${selected ? 'bg-indigo-50/80 dark:bg-indigo-950/30' : 'hover:bg-slate-50 dark:hover:bg-slate-800/40'}`} onClick={() => onSelect(row.doc_id, row.pipeline_id, row.trace_id)}>
          <td className="p-2"><span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${meta.className}`}>{meta.label}</span></td>
          <td className="p-2 max-w-[18rem]"><p className="line-clamp-2 text-ink" title={row.doc_preview ?? undefined}>{row.doc_preview?.trim() || <span className="italic text-ink-faint">Preview unavailable or redacted</span>}</p></td>
          <td className="p-2 font-mono text-[11px]">{row.pipeline_id}</td><td className="p-2">{row.outcome_evidence ?? 'unavailable'}</td><td className="p-2 font-mono">{row.dropped_at ?? '—'}</td>
          <td className="p-2 max-w-[10rem]">{row.drop_reason ?? '—'}{row.drop_reason_inferred ? <span className="ml-1 text-[10px] text-ink-faint">(legacy inferred)</span> : null}</td><td className="p-2 font-mono">{row.final_rank ?? '—'}</td><td className="p-2 font-mono text-[10px] text-ink-faint">{row.doc_id}</td>
        </tr>
      })}</tbody>
    </table></div>}
  </section>
}
