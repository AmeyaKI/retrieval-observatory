import { InvestigationStage, StageSummary } from '../api'
import { OP_ACCENT, OP_LABEL } from '../utils/opTypeColors'

// The selected operator, read from the investigation envelopes only: the stored aggregate over
// every trace of the scope and, when one query is open, that trace's span. Every count is shown
// with its denominator; skipped invocations are reported as skipped, never as zero quality.

export interface OperatorInspectorProps {
  /** The operator node id (`stage` URL parameter). */
  opId: string
  /** The selected trace's span at this operator; null in aggregate views or when the trace did not run it. */
  stage: InvestigationStage | null
  /** Stored per-scope aggregate; null before the projection is built. */
  aggregate: StageSummary | null
}

export const STATUS_GLYPHS: Record<string, string> = {
  FIRED: '●',
  SKIPPED_BY_GATE: '⊘',
  ERROR: '✕',
  TIMEOUT: '⏱',
}

export function statusGlyph(status: string): string {
  return STATUS_GLYPHS[status] ?? '·'
}

export function captureGlyph(capture: string): string {
  if (capture === 'recorded' || capture === 'not_applicable') return ''
  if (capture === 'unavailable') return '✕'
  return '⚠'
}

function Count({ label, value, of, unit }: { label: string; value: number; of?: number | null; unit: string }) {
  return (
    <div>
      <dt className="text-ink-faint">{label}</dt>
      <dd className="font-mono tabular-nums text-ink">
        {value}
        {of != null && <span className="text-ink-muted"> of {of}</span>} <span className="font-sans text-ink-muted">{unit}</span>
      </dd>
    </div>
  )
}

export default function OperatorInspector({ opId, stage, aggregate }: OperatorInspectorProps) {
  const opType = stage?.op_type ?? null
  const accent = OP_ACCENT[opType ?? ''] ?? OP_ACCENT.TRANSFORM
  const operatorId = stage?.operator_id ?? aggregate?.operator_id ?? null
  const invocations = aggregate ? aggregate.queries_served + aggregate.queries_skipped : null
  return (
    <section aria-labelledby="operator-inspector-title" className="app-inset p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="operator-inspector-title" className="font-mono font-semibold text-ink">
          {opId}
        </h3>
        {opType && (
          <span className="rounded px-1.5 py-0.5 text-[10px]" style={{ background: accent.fill, color: accent.text }}>
            {OP_LABEL[opType] ?? opType}
          </span>
        )}
        {operatorId && operatorId !== opId && <span className="text-ink-faint">operator {operatorId}</span>}
        {stage?.branch && <span className="text-ink-faint">branch {stage.branch}</span>}
      </div>
      {aggregate ? (
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
          <Count label="Served" value={aggregate.queries_served} of={invocations} unit="queries" />
          <Count label="Skipped by gate" value={aggregate.queries_skipped} of={invocations} unit="queries" />
          <Count label="Received" value={aggregate.candidates_received} unit={`candidates over ${aggregate.queries_served} served queries`} />
          <Count label="Removed" value={aggregate.removal_events} unit="events" />
          <Count label="Introduced" value={aggregate.introduced} unit="events" />
          <Count label="Partial boundaries" value={aggregate.partial_boundaries} of={aggregate.queries_served} unit="served queries" />
        </dl>
      ) : (
        <p className="mt-2 text-ink-muted">No stored aggregate for this operator; index the run to count served queries and candidates.</p>
      )}
      {stage && (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 border-t border-hairline pt-2 sm:grid-cols-3">
          <div>
            <dt className="text-ink-faint">This query</dt>
            <dd className="text-ink">
              <span aria-hidden="true">{statusGlyph(stage.status)}</span> {stage.status}
            </dd>
          </div>
          <div>
            <dt className="text-ink-faint">Input capture</dt>
            <dd className="text-ink">
              {captureGlyph(stage.input_capture) && <span aria-hidden="true">{captureGlyph(stage.input_capture)} </span>}
              {stage.input_capture}
            </dd>
          </div>
          <div>
            <dt className="text-ink-faint">Output capture</dt>
            <dd className="text-ink">
              {captureGlyph(stage.output_capture) && <span aria-hidden="true">{captureGlyph(stage.output_capture)} </span>}
              {stage.output_capture}
            </dd>
          </div>
          <Count label="Received" value={stage.received} unit="candidates" />
          <Count label="Emitted" value={stage.emitted} unit="candidates" />
          <Count label="Removed / introduced" value={stage.removed} unit={`removed · ${stage.introduced} introduced`} />
        </dl>
      )}
    </section>
  )
}
