import { InvestigationStage, JourneyRow } from '../api'
import { contentPreview, entityKey, evidenceLabel, KIND_GLYPHS, outcomeGlyph, outcomeLabel } from '../utils/queryDebugger'
import { captureGlyph } from './OperatorInspector'

// The selected journey: what was judged, where it ended, every recorded transition in order with
// its evidence label, the capture state of each boundary it crossed, content when captured, and
// the permalink. Digests and ids sit behind a disclosure.

export interface InvestigationDetailProps {
  row: JourneyRow
  /** The selected trace's spans (query view); null in document views or before a trace is chosen. */
  stages: InvestigationStage[] | null
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-ink-faint">{label}</dt>
      <dd className="text-ink">{children}</dd>
    </div>
  )
}

function rank(value: number | null): string {
  return value == null ? '—' : `#${value}`
}

function copy(text: string): void {
  if (typeof navigator !== 'undefined' && navigator.clipboard) void navigator.clipboard.writeText(text).catch(() => undefined)
}

export default function InvestigationDetail({ row, stages }: InvestigationDetailProps) {
  const preview = contentPreview(row)
  const byOp = new Map((stages ?? []).map((stage) => [stage.op_id, stage]))
  const crossed = [...new Set(row.events.map((event) => event.op_id))].filter((opId) => byOp.has(opId))
  const technical: Array<[string, string]> = [
    ['Trace', row.trace_id],
    ['Trace digest', row.trace_digest],
    ['Evaluation digest', row.evaluation_digest],
    ['Judgment digest', row.judgment_digest],
    ['Derivation', row.derivation_version],
    ['Schema', String(row.schema_version)],
    ['Confusion', row.confusion],
    ['Priority', String(row.priority)],
    ['Occurrences', row.occurrence_entity_ids.join(', ')],
    ['Entity revision', row.entity_revision ?? '—'],
  ]
  return (
    <section aria-labelledby="journey-detail-title" className="app-card space-y-4 p-4 text-sm">
      <header className="space-y-2">
        <h2 id="journey-detail-title" className="font-semibold text-ink">
          <span className="font-mono">{entityKey(row)}</span> <span className="font-normal text-ink-muted">in query</span> <span className="font-mono">{row.query_id}</span>
        </h2>
        <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Judgment">
            {row.judgment}
            {row.grade != null && ` · grade ${row.grade}`}
            {row.judgment_source && <span className="text-ink-muted"> ({row.judgment_source})</span>}
          </Field>
          <Field label="Final membership">
            {row.final_membership} · rank {rank(row.final_rank)}
          </Field>
          <Field label="Outcome">
            <span aria-hidden="true">{outcomeGlyph(row.outcome)}</span> {outcomeLabel(row.outcome)}
          </Field>
          <Field label="Capture">
            {row.capture_state === 'partial' && <span aria-hidden="true">⚠ </span>}
            {row.capture_state}
            {row.loss_boundary && (
              <span className="text-ink-muted">
                {' '}
                · loss boundary <span className="font-mono">{row.loss_boundary}</span>
              </span>
            )}
          </Field>
        </dl>
      </header>

      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Recorded transitions</h3>
        {row.events.length === 0 ? (
          <p className="mt-1 text-ink-muted">Not observed at any captured boundary.</p>
        ) : (
          <ol className="mt-1 divide-y divide-hairline">
            {row.events.map((event, index) => {
              const incomplete = event.kind === 'unknown' || !event.boundary_complete
              return (
                <li key={`${event.op_id}-${event.candidate_id}-${index}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5 text-xs">
                  <span className="w-5 text-right tabular-nums text-ink-faint">{index + 1}</span>
                  <span className="font-mono text-ink">{event.op_id}</span>
                  <span className="text-ink">
                    <span aria-hidden="true">{KIND_GLYPHS[event.kind]}</span> {event.kind}
                  </span>
                  <span className="tabular-nums text-ink-muted">
                    {rank(event.input_rank)} → {rank(event.output_rank)}
                  </span>
                  {event.reason && (
                    <span className="text-ink-muted">
                      {event.reason} <span className="text-ink-faint">({evidenceLabel(event.reason_evidence)})</span>
                    </span>
                  )}
                  {!event.reason && event.kind === 'removed' && <span className="text-ink-faint">no reason recorded ({evidenceLabel(event.reason_evidence)})</span>}
                  {incomplete && (
                    <span className="text-status-warning">
                      <span aria-hidden="true">⚠</span> boundary not fully captured
                    </span>
                  )}
                  {event.branch && <span className="text-ink-faint">branch {event.branch}</span>}
                  <details className="text-ink-faint">
                    <summary className="cursor-pointer">ids</summary>
                    <span className="font-mono">
                      invocation {event.invocation_id ?? '—'} · candidate {event.candidate_id} · occurrence {event.occurrence_entity_id} · input evidence {event.input_evidence}
                      {event.source_occurrences.length > 0 && ` · from ${event.source_occurrences.join(', ')}`}
                    </span>
                  </details>
                </li>
              )
            })}
          </ol>
        )}
      </div>

      {crossed.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Boundary capture</h3>
          <ul className="mt-1 space-y-0.5 text-xs">
            {crossed.map((opId) => {
              const stage = byOp.get(opId)!
              return (
                <li key={opId} className="flex flex-wrap gap-x-3">
                  <span className="font-mono text-ink">{opId}</span>
                  <span className="text-ink-muted">
                    in {captureGlyph(stage.input_capture) && <span aria-hidden="true">{captureGlyph(stage.input_capture)} </span>}
                    {stage.input_capture} · out {captureGlyph(stage.output_capture) && <span aria-hidden="true">{captureGlyph(stage.output_capture)} </span>}
                    {stage.output_capture}
                  </span>
                  <span className="text-ink-faint">source {stage.source_ref ?? 'not recorded'}</span>
                  {stage.params && Object.keys(stage.params).length > 0 && (
                    <details className="basis-full">
                      <summary className="cursor-pointer text-ink-faint">Recorded configuration ({Object.keys(stage.params).length})</summary>
                      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px]">
                        {Object.entries(stage.params).map(([key, value]) => (
                          <div key={key} className="contents">
                            <dt className="text-ink-faint">{key}</dt>
                            <dd className="text-ink break-all">{typeof value === 'string' ? value : JSON.stringify(value)}</dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      )}

      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Content</h3>
        {preview ? <blockquote className="mt-1 whitespace-pre-wrap border-l-2 border-hairline pl-3 text-ink">{preview}</blockquote> : <p className="mt-1 text-ink-muted">no content captured; IDs only</p>}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label htmlFor="journey-permalink" className="text-ink-faint">
          Permalink
        </label>
        <input id="journey-permalink" readOnly value={row.investigation_link} className="min-w-0 flex-1 rounded border border-hairline bg-surface-muted px-2 py-1 font-mono text-ink" />
        <button type="button" onClick={() => copy(row.investigation_link)} className="rounded border border-hairline px-2 py-1 text-ink hover:bg-surface-muted">
          Copy
        </button>
      </div>

      <details className="app-inset p-3 text-xs">
        <summary className="cursor-pointer font-medium text-ink">Evidence details</summary>
        <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
          {technical.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-3">
              <dt className="text-ink-faint">{label}</dt>
              <dd className="truncate font-mono text-ink" title={value}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  )
}
