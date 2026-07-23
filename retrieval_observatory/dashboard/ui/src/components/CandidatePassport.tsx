import { CandidateLineageNode } from '../api'

export default function CandidatePassport({ candidate }: { candidate: CandidateLineageNode | null }) {
  if (!candidate) return <section aria-labelledby="candidate-passport-heading"><h3 id="candidate-passport-heading" className="text-sm font-semibold">Candidate passport</h3><p className="text-xs text-ink-muted">Select a recorded candidate to inspect its evidence.</p></section>
  return (
    <section aria-labelledby="candidate-passport-heading" className="rounded border border-slate-200 dark:border-slate-700 p-3 space-y-3">
      <div><h3 id="candidate-passport-heading" className="text-sm font-semibold">Candidate passport · <span className="font-mono">{candidate.candidate_id}</span></h3><p className="text-xs text-ink-muted">Trace-qualified identity: <span className="font-mono">{candidate.node_id}</span></p></div>
      <dl className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <div><dt className="text-ink-faint">Outcome</dt><dd className="font-semibold">{candidate.outcome.kind.replace(/_/g, ' ')}</dd></div>
        <div><dt className="text-ink-faint">Relevance</dt><dd>{candidate.relevance.kind}{candidate.relevance.kind === 'unknown' ? ' (evidence unavailable)' : candidate.relevance.grade != null ? ` · grade ${candidate.relevance.grade}` : ''}</dd></div>
        <div><dt className="text-ink-faint">Source document</dt><dd className="font-mono">{candidate.source.document_id ?? 'unavailable'}</dd></div>
        <div><dt className="text-ink-faint">Document revision</dt><dd className="font-mono">{candidate.source.document_revision ?? candidate.source.content_hash ?? 'unavailable'}</dd></div>
        <div><dt className="text-ink-faint">Lineage evidence</dt><dd>{candidate.lineage_evidence}</dd></div>
        <div><dt className="text-ink-faint">Removal</dt><dd>{candidate.removed_at ?? 'not recorded'} · {candidate.removal_evidence}</dd></div>
        <div><dt className="text-ink-faint">Exit reason</dt><dd>{candidate.removal_reason ?? candidate.outcome.reason ?? 'not recorded'}</dd></div>
        <div><dt className="text-ink-faint">Chunk offsets</dt><dd className="font-mono">{candidate.source.char_start != null && candidate.source.char_end != null ? `${candidate.source.char_start}–${candidate.source.char_end}` : 'unavailable'}</dd></div>
        <div><dt className="text-ink-faint">Parents</dt><dd className="font-mono">{candidate.parent_candidate_ids.join(', ') || 'none recorded'}</dd></div>
        <div><dt className="text-ink-faint">Derived children</dt><dd className="font-mono">{candidate.derived_child_ids.join(', ') || 'none recorded'}</dd></div>
      </dl>
      {candidate.source.preview ? <p className="rounded bg-surface-muted p-2 text-xs">{candidate.source.preview}</p> : <p className="text-xs italic text-ink-faint">Preview unavailable or omitted by capture policy.</p>}
      <div className="space-y-2">{candidate.routes.map((route, index) => <div key={index} className="rounded bg-surface-muted p-2 text-xs"><p className="font-semibold">Route {index + 1} · {route.lineage_evidence}</p><ol className="mt-1 space-y-1">{route.stages.map(stage => <li key={`${stage.op_id}:${stage.branch_id ?? ''}`}><span className="font-mono">{stage.op_id}</span> · {stage.branch_id ?? 'main'} · input → output rank {stage.input_rank ?? '—'} → {stage.output_rank ?? stage.rank} · score {stage.score}{stage.score_type ? ` (${stage.score_type}${stage.score_model ? ` · ${stage.score_model}` : ''})` : ''}{Object.keys(stage.score_components).length ? ` · components ${Object.entries(stage.score_components).map(([key, value]) => `${key}=${value}`).join(', ')}` : ''}</li>)}</ol></div>)}</div>
    </section>
  )
}
