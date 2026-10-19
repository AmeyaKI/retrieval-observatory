import { InvestigationStage, JourneyRow, PipelineGraph } from '../api'
import { journeySteps, StepTone } from '../utils/journeyWords'
import { contentPreview, displayEntity, evidenceLabel, outcomeText, outcomeTone } from '../utils/queryDebugger'
import { BADGE } from './InvestigationGraph'

// One document's journey card: its id and outcome, then (expanded) the numbered steps in words.
// Collapsed, the whole card is a button that selects the document. The recorded transitions with
// their raw kinds, boundary capture, configuration, ids, digests and the permalink sit behind
// "Technical details".

export interface JourneyCardProps {
  row: JourneyRow
  graph: PipelineGraph | null
  /** The question's spans (one trace); null in document views or before a trace is chosen. */
  stages: InvestigationStage[] | null
  k: number | null
  expanded: boolean
  /** Carries `#journey-detail-title` and names the card as a region: one card per page. */
  isHeading: boolean
  singleNamespace: boolean
  onSelect?: () => void
}

const BUBBLE: Record<StepTone, string> = { ...BADGE, faint: 'border border-dashed border-hairline text-ink-faint' }
const FOCUS_RING = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent'

function rank(value: number | null): string {
  return value == null ? '—' : `#${value}`
}

function copy(text: string): void {
  if (typeof navigator !== 'undefined' && navigator.clipboard) void navigator.clipboard.writeText(text).catch(() => undefined)
}

export function OutcomePill({ row, k }: { row: JourneyRow; k: number | null }) {
  return <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ${BADGE[outcomeTone(row.outcome)]}`}>{outcomeText(row, k)}</span>
}

function bestRank(row: JourneyRow): number | null {
  const ranks = row.events.map((event) => event.output_rank).filter((value): value is number => value != null)
  return ranks.length ? Math.min(...ranks) : null
}

export default function JourneyCard({ row, graph, stages, k, expanded, isHeading, singleNamespace, onSelect }: JourneyCardProps) {
  const id = displayEntity(row, singleNamespace)
  if (!expanded) {
    const best = bestRank(row)
    return (
      <button
        type="button"
        onClick={onSelect}
        className={`flex w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-hairline bg-surface px-3 py-2 text-left hover:bg-surface-muted ${FOCUS_RING}`}
      >
        <span className="break-all font-mono text-sm font-semibold text-ink">{id}</span>
        <OutcomePill row={row} k={k} />
        {best != null && <span className="ml-auto text-xs tabular-nums text-ink-muted">Best rank #{best}</span>}
      </button>
    )
  }
  const steps = journeySteps(row, graph, stages, k)
  const Wrapper = isHeading ? 'section' : 'div'
  return (
    <Wrapper aria-labelledby={isHeading ? 'journey-detail-title' : undefined} className="rounded-lg border border-accent/50 bg-surface p-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={isHeading ? 'journey-detail-title' : undefined} className="break-all font-mono text-sm font-semibold text-ink">
          {id}
          <span className="sr-only"> in question {row.query_id}</span>
        </h3>
        <OutcomePill row={row} k={k} />
      </div>
      <ol className="mt-3 space-y-3">
        {steps.map((step, index) => (
          <li key={`${step.opId ?? 'final'}-${index}`} className="flex gap-3">
            <span aria-hidden="true" className={`mt-px flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums ${BUBBLE[step.tone]}`}>
              {index + 1}
            </span>
            <div className="min-w-0">
              <p className="text-ink">
                {step.name && step.text.startsWith(step.name) ? (
                  <>
                    <span className="font-semibold">{step.name}</span>
                    {step.text.slice(step.name.length)}
                  </>
                ) : (
                  step.text
                )}
              </p>
              {step.sub && <p className="text-xs text-ink-muted">{step.sub}</p>}
            </div>
          </li>
        ))}
      </ol>
      <TechnicalDetails row={row} stages={stages} />
    </Wrapper>
  )
}

function TechnicalDetails({ row, stages }: { row: JourneyRow; stages: InvestigationStage[] | null }) {
  const preview = contentPreview(row)
  const byOp = new Map((stages ?? []).map((stage) => [stage.op_id, stage]))
  const crossed = [...new Set(row.events.map((event) => event.op_id))].filter((opId) => byOp.has(opId))
  const facts: Array<[string, string]> = [
    ['Judgment', `${row.judgment}${row.grade != null ? ` · grade ${row.grade}` : ''}${row.judgment_source ? ` (${row.judgment_source})` : ''}`],
    ['Final membership', `${row.final_membership} · rank ${rank(row.final_rank)}`],
    ['Outcome', row.outcome],
    ['Capture', `${row.capture_state}${row.loss_boundary ? ` · loss boundary ${row.loss_boundary}` : ''}`],
    ['Entity', `${row.namespace}:${row.entity_id}`],
    ['Trace', row.trace_id],
    ['Trace digest', row.trace_digest],
    ['Evaluation digest', row.evaluation_digest],
    ['Judgment digest', row.judgment_digest],
    ['Derivation', row.derivation_version],
    ['Schema', String(row.schema_version)],
    ['Confusion', row.confusion],
    ['Priority', String(row.priority)],
    ['Occurrences', row.occurrence_entity_ids.join(', ') || '—'],
    ['Entity revision', row.entity_revision ?? '—'],
  ]
  return (
    <details className="mt-3 text-xs">
      <summary className="cursor-pointer text-ink-muted">Technical details</summary>
      <div className="mt-2 space-y-3">
        <div>
          <h4 className="font-semibold text-ink-muted">Recorded transitions</h4>
          {row.events.length === 0 ? (
            <p className="mt-1 text-ink-muted">Not observed at any captured boundary.</p>
          ) : (
            <ol className="mt-1 divide-y divide-hairline">
              {row.events.map((event, index) => (
                <li key={`${event.op_id}-${event.candidate_id}-${index}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5">
                  <span className="w-5 text-right tabular-nums text-ink-faint">{index + 1}</span>
                  <span className="font-mono text-ink">{event.op_id}</span>
                  <span className="text-ink">{event.kind}</span>
                  <span className="tabular-nums text-ink-muted">
                    {rank(event.input_rank)} → {rank(event.output_rank)}
                  </span>
                  {event.reason && (
                    <span className="text-ink-muted">
                      {event.reason} <span className="text-ink-faint">({evidenceLabel(event.reason_evidence)})</span>
                    </span>
                  )}
                  {!event.reason && event.kind === 'removed' && <span className="text-ink-faint">no reason recorded ({evidenceLabel(event.reason_evidence)})</span>}
                  {(event.kind === 'unknown' || !event.boundary_complete) && <span className="text-status-warning">boundary not fully captured</span>}
                  {event.branch && <span className="text-ink-faint">branch {event.branch}</span>}
                  <span className="basis-full break-all pl-8 font-mono text-ink-faint">
                    invocation {event.invocation_id ?? '—'} · candidate {event.candidate_id} · occurrence {event.occurrence_entity_id} · input evidence {event.input_evidence}
                    {event.source_occurrences.length > 0 && ` · from ${event.source_occurrences.join(', ')}`}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </div>

        {crossed.length > 0 && (
          <div>
            <h4 className="font-semibold text-ink-muted">Boundary capture</h4>
            <ul className="mt-1 space-y-0.5">
              {crossed.map((opId) => {
                const stage = byOp.get(opId)!
                return (
                  <li key={opId} className="flex flex-wrap gap-x-3">
                    <span className="font-mono text-ink">{opId}</span>
                    <span className="text-ink-muted">
                      in {stage.input_capture} · out {stage.output_capture}
                    </span>
                    <span className="text-ink-faint">source {stage.source_ref ?? 'not recorded'}</span>
                    {stage.params && Object.keys(stage.params).length > 0 && (
                      <dl className="mt-0.5 grid basis-full grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 pl-4 font-mono">
                        {Object.entries(stage.params).map(([key, value]) => (
                          <div key={key} className="contents">
                            <dt className="text-ink-faint">{key}</dt>
                            <dd className="break-all text-ink">{typeof value === 'string' ? value : JSON.stringify(value)}</dd>
                          </div>
                        ))}
                      </dl>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        )}

        <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
          {facts.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-3">
              <dt className="shrink-0 text-ink-faint">{label}</dt>
              <dd className="truncate font-mono text-ink" title={value}>
                {value}
              </dd>
            </div>
          ))}
        </dl>

        <p className="text-ink-muted">{preview ? <span className="whitespace-pre-wrap text-ink">{preview}</span> : 'No content captured; ids only.'}</p>

        <div className="flex flex-wrap items-center gap-2">
          <label className="flex min-w-0 flex-1 items-center gap-2 text-ink-faint">
            Permalink
            <input readOnly value={row.investigation_link} className="min-w-0 flex-1 rounded border border-hairline bg-surface-muted px-2 py-1 font-mono text-ink" />
          </label>
          <button type="button" onClick={() => copy(row.investigation_link)} className={`rounded border border-hairline px-2 py-1 text-ink hover:bg-surface-muted ${FOCUS_RING}`}>
            Copy
          </button>
        </div>
      </div>
    </details>
  )
}
