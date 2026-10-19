import { FlowStep, InvestigationFlow, InvestigationStage, PipelineGraphNode, StageSummary } from '../api'
import { captureWord, plural, statusWord, stepKind, stepName } from '../utils/flowWords'

// The selected step in plain words: what it did with the run's correct documents and, when one
// question is open, what it did for that question. The stored counts and raw states stay in
// "Technical details". Skipped invocations are reported as skipped, never as zero quality.

export interface OperatorInspectorProps {
  /** The step's node id (`stage` URL parameter). */
  opId: string
  /** The diagram's node for the step (folded when repeated invocations are collapsed). */
  node: PipelineGraphNode | null
  /** The step's correct-document counts, folded like the node; null without a flow. */
  flowStep: FlowStep | null
  flow: InvestigationFlow | null
  /** The open question's span at this step; null in run views or when the question did not run it. */
  stage: InvestigationStage | null
  /** Stored per-scope aggregate; null before the projection is built. */
  aggregate: StageSummary | null
}

/** Kept for the journey detail, which marks partial or missing capture next to the raw value. */
export function captureGlyph(capture: string): string {
  if (capture === 'recorded' || capture === 'not_applicable') return ''
  if (capture === 'unavailable') return '✕'
  return '⚠'
}

function runSentence(node: PipelineGraphNode | null, step: FlowStep, flow: InvestigationFlow, aggregate: StageSummary | null): string {
  const k = flow.k
  const ran = aggregate
    ? `Ran for ${aggregate.queries_served} of ${plural(aggregate.queries_served + aggregate.queries_skipped, 'question')}. `
    : node
      ? `Ran for ${node.status_counts.FIRED ?? 0} of ${plural(Object.values(node.status_counts).reduce((a, b) => a + b, 0), 'question')}. `
      : ''
  const got =
    node?.op_type === 'SOURCE'
      ? `Found ${plural(step.seen, 'correct document')}, ${step.in_top_k} in its own top ${k}`
      : `Received ${plural(step.input, 'correct document')}`
  const parts = [
    step.lost.pushed_out > 0 ? `${step.lost.pushed_out} pushed out of the top ${k}` : null,
    step.lost.ranked_low > 0 ? `${step.lost.ranked_low} ranked too low` : null,
    step.lost.dropped > 0 ? `${step.lost.dropped} dropped` : null,
  ].filter(Boolean)
  const lost = step.lost_total > 0 ? ` and lost ${step.lost_total} for good${parts.length > 0 ? `: ${parts.join(', ')}` : ''}.` : ' and lost none.'
  const removed = step.removed > step.lost_total ? ` It removed ${step.removed}; ${step.removed_but_delivered} still reached the top ${k}.` : ''
  return `${ran}${got}${lost}${removed}`
}

function questionSentence(stage: InvestigationStage): string {
  const capture = [
    ['Input', captureWord(stage.input_capture)],
    ['Output', captureWord(stage.output_capture)],
  ]
    .filter(([, word]) => word === 'Partly recorded' || word === 'Not recorded')
    .map(([side, word]) => ` ${side} ${word.toLowerCase()}.`)
    .join('')
  return `For this question: ${statusWord(stage.status)}. ${stage.received} candidates in, ${stage.emitted} out.${capture}`
}

export default function OperatorInspector({ opId, node, flowStep, flow, stage, aggregate }: OperatorInspectorProps) {
  const { name, id } = node ? stepName(node) : { name: opId, id: null }
  const kind = stepKind(node?.op_type ?? stage?.op_type ?? '')
  const counted = flow && flow.totals.relevant > 0 && flowStep ? flowStep : null
  const source = (node?.op_type ?? stage?.op_type) === 'SOURCE'
  const operatorId = stage?.operator_id ?? aggregate?.operator_id ?? null
  const details: Array<[string, string | number]> = []
  if (aggregate) {
    details.push(
      ['Questions served', aggregate.queries_served],
      ['Questions skipped by a gate', aggregate.queries_skipped],
      ['Candidates received', aggregate.candidates_received],
      ['Removal events', aggregate.removal_events],
      ['Introduced', aggregate.introduced],
      ['Partial boundaries', aggregate.partial_boundaries],
    )
  }
  if (operatorId && operatorId !== opId) details.push(['Operator', operatorId])
  if (stage) {
    details.push(['Status', stage.status], ['Input capture', stage.input_capture], ['Output capture', stage.output_capture])
    if (stage.branch) details.push(['Branch', stage.branch])
    if (stage.source_ref) details.push(['Source', stage.source_ref])
    for (const [key, value] of Object.entries(stage.params ?? {})) details.push([key, typeof value === 'string' ? value : JSON.stringify(value)])
  }
  return (
    <section aria-labelledby="operator-inspector-title" className="app-inset space-y-2 p-3 text-sm">
      <h3 id="operator-inspector-title" className="font-semibold text-ink">
        {name} <span className="font-normal text-ink-muted">· {kind}</span>
        {id && <span className="ml-2 font-mono text-xs font-normal text-ink-faint">{id}</span>}
      </h3>
      {counted && flow ? (
        <p className="text-ink">{runSentence(node, counted, flow, aggregate)}</p>
      ) : aggregate ? (
        <p className="text-ink">
          Ran for {aggregate.queries_served} of {plural(aggregate.queries_served + aggregate.queries_skipped, 'question')};{' '}
          {source ? `${aggregate.introduced} candidates found.` : `${aggregate.candidates_received} candidates in.`}
        </p>
      ) : (
        <p className="text-ink-muted">No stored counts for this step yet; index the run to count them.</p>
      )}
      {stage && <p className="text-ink">{questionSentence(stage)}</p>}
      {details.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer font-medium text-accent">Technical details</summary>
          <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
            {details.map(([label, value], index) => (
              <div key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                <dt className="text-ink-faint">{label}</dt>
                <dd className="truncate font-mono tabular-nums text-ink" title={String(value)}>
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </section>
  )
}
