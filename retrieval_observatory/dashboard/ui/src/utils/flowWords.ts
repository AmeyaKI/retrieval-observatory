import { FlowStep, InvestigationFlow, InvestigationStage, JourneyEvent, PipelineGraph, PipelineGraphNode, StageSummary } from '../api'
import { collapsedNodeId } from './dagLayout'

// Plain words for the pipeline diagram and the step panel. Internal enum values (FIRED,
// SKIPPED_BY_GATE, capture states, op types) never reach a card; they stay in "Technical details".

export type Tone = 'negative' | 'positive' | 'neutral' | 'warning' | 'accent'

export interface Badge {
  tone: Tone
  text: string
}

/** What one card says: a metric line, a badge, a note (one tone for the whole note) and whether it is a ghost. */
export interface CardWords {
  metric: string
  note: string | null
  noteTone: Tone | null
  badge: Badge | null
  ghost: boolean
}

const KIND: Record<string, string> = {
  SOURCE: 'Retrieval',
  FUSE: 'Fusion',
  RERANK: 'Reranking',
  BOOST: 'Boost',
  EXPAND: 'Expansion',
  FILTER: 'Filter',
  GATE: 'Gate',
  TRANSFORM: 'Step',
  GENERATE: 'Generation',
}

export function stepKind(opType: string): string {
  return KIND[opType] ?? 'Step'
}

const STATUS: Record<string, string> = { FIRED: 'Ran', SKIPPED_BY_GATE: 'Skipped by a gate', ERROR: 'Failed', TIMEOUT: 'Timed out' }

export function statusWord(status: string): string {
  return STATUS[status] ?? status.toLowerCase().replace(/_/g, ' ')
}

export function captureWord(capture: string): string {
  if (capture === 'recorded') return 'Recorded'
  if (capture === 'not_applicable') return ''
  if (capture === 'unavailable') return 'Not recorded'
  return 'Partly recorded'
}

/** "Rerank (rerank@dense)" → Rerank + rerank@dense; a short label keeps its id unless it already names it. */
export function stepName(node: Pick<PipelineGraphNode, 'label' | 'node_id'>): { name: string; id: string | null } {
  const label = node.label || node.node_id
  if (label.length <= 16) return { name: label, id: label.includes(node.node_id) ? null : node.node_id }
  const suffix = `(${node.node_id})`
  if (label.endsWith(suffix)) return { name: label.slice(0, -suffix.length).trim(), id: node.node_id }
  return { name: label, id: label === node.node_id ? null : node.node_id }
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}

const ZERO_STEP: FlowStep = {
  seen: 0,
  input: 0,
  output: 0,
  in_top_k: 0,
  removed: 0,
  removed_but_delivered: 0,
  lost: { dropped: 0, ranked_low: 0, pushed_out: 0, unknown: 0 },
  lost_total: 0,
}

function addSteps(a: FlowStep, b: FlowStep): FlowStep {
  return {
    seen: a.seen + b.seen,
    input: a.input + b.input,
    output: a.output + b.output,
    in_top_k: a.in_top_k + b.in_top_k,
    removed: a.removed + b.removed,
    removed_but_delivered: a.removed_but_delivered + b.removed_but_delivered,
    lost: {
      dropped: a.lost.dropped + b.lost.dropped,
      ranked_low: a.lost.ranked_low + b.lost.ranked_low,
      pushed_out: a.lost.pushed_out + b.lost.pushed_out,
      unknown: a.lost.unknown + b.lost.unknown,
    },
    lost_total: a.lost_total + b.lost_total,
  }
}

/** Collapsed: `op#N` step counts and co-presence pairs fold onto `op` (self-pairs dropped). */
export function foldFlow(flow: InvestigationFlow | null, collapsed: boolean): InvestigationFlow | null {
  if (!flow || !collapsed) return flow
  const steps: Record<string, FlowStep> = {}
  for (const [id, step] of Object.entries(flow.steps)) {
    const key = collapsedNodeId(id)
    steps[key] = addSteps(steps[key] ?? ZERO_STEP, step)
  }
  const copresence: Record<string, number> = {}
  for (const [pair, count] of Object.entries(flow.copresence)) {
    const split = pair.indexOf('→')
    const source = collapsedNodeId(pair.slice(0, split))
    const target = collapsedNodeId(pair.slice(split + 1))
    if (source === target) continue
    copresence[`${source}→${target}`] = (copresence[`${source}→${target}`] ?? 0) + count
  }
  return { ...flow, steps, copresence }
}

/** A step absent from a loaded flow saw no correct document: zeros, not "unknown". */
export function flowStepOf(flow: InvestigationFlow | null, nodeId: string): FlowStep | null {
  return flow ? flow.steps[nodeId] ?? ZERO_STEP : null
}

/** The stored aggregates that fold onto the node, summed. */
export function foldedAggregate(stages: StageSummary[] | null, nodeId: string, collapsed: boolean): StageSummary | null {
  const found = (stages ?? []).filter((stage) => (collapsed ? collapsedNodeId(stage.op_id) : stage.op_id) === nodeId)
  if (found.length === 0) return null
  return found.slice(1).reduce(
    (sum, stage) => ({
      ...sum,
      queries_served: sum.queries_served + stage.queries_served,
      queries_skipped: sum.queries_skipped + stage.queries_skipped,
      candidates_received: sum.candidates_received + stage.candidates_received,
      removal_events: sum.removal_events + stage.removal_events,
      introduced: sum.introduced + stage.introduced,
      partial_boundaries: sum.partial_boundaries + stage.partial_boundaries,
    }),
    { ...found[0], op_id: nodeId },
  )
}

const STATUS_PRIORITY = ['ERROR', 'TIMEOUT', 'FIRED', 'SKIPPED_BY_GATE']

/** One question's span(s) at the node; repeated invocations are summed, the worst status and capture win. */
export function foldedStage(stages: InvestigationStage[] | null, nodeId: string, collapsed: boolean): InvestigationStage | undefined {
  const found = (stages ?? []).filter((stage) => (collapsed ? collapsedNodeId(stage.op_id) : stage.op_id) === nodeId)
  if (found.length <= 1) return found[0]
  const rank = (status: string) => (STATUS_PRIORITY.includes(status) ? STATUS_PRIORITY.indexOf(status) : 2)
  const worst = (capture: (s: InvestigationStage) => string) => found.map(capture).find((c) => c !== 'recorded' && c !== 'not_applicable') ?? capture(found[0])
  return {
    ...found[0],
    op_id: nodeId,
    status: [...found].sort((a, b) => rank(a.status) - rank(b.status))[0].status,
    input_capture: worst((s) => s.input_capture),
    output_capture: worst((s) => s.output_capture),
    received: found.reduce((sum, s) => sum + s.received, 0),
    emitted: found.reduce((sum, s) => sum + s.emitted, 0),
    removed: found.reduce((sum, s) => sum + s.removed, 0),
    introduced: found.reduce((sum, s) => sum + s.introduced, 0),
  }
}

/** Questions the step ran for, from the graph's status counts. */
export function firedCount(node: PipelineGraphNode, traceCount: number): number {
  return node.status_counts.FIRED ?? Math.round(node.fire_rate * traceCount)
}

function join(parts: Array<string | null>): string | null {
  const kept = parts.filter((part): part is string => Boolean(part))
  return kept.length > 0 ? kept.join(' · ') : null
}

/** Run mode: correct documents over the whole run (or the stored candidate counts without judgments).
 * `separateResult`: a result card follows the final step, so the step carries only its own facts. */
export function runCard(
  node: PipelineGraphNode,
  step: FlowStep | null,
  flow: InvestigationFlow | null,
  graph: PipelineGraph,
  aggregate: StageSummary | null,
  separateResult = false,
): CardWords {
  const ghost = node.fire_rate < 1
  const ranFor = `Ran for ${firedCount(node, graph.trace_count)} of ${plural(graph.trace_count, 'question')}`
  const source = node.op_type === 'SOURCE'
  if (!flow || flow.totals.relevant === 0) {
    if (!aggregate) return { metric: ranFor, note: null, noteTone: null, badge: null, ghost }
    const served = aggregate.queries_served
    return {
      metric: `Ran for ${served} of ${plural(served + aggregate.queries_skipped, 'question')}`,
      note: source ? `${aggregate.introduced} candidates found` : `${aggregate.candidates_received} candidates in`,
      noteTone: null,
      badge: null,
      ghost,
    }
  }
  const s = step ?? ZERO_STEP
  const { k, totals } = flow
  const metric = source ? `Found ${s.seen} of ${totals.relevant}` : s.input === 0 ? 'None reached it' : `${s.input} correct in`
  let badge: Badge | null = null
  let removal: string | null = null
  if (s.lost_total > 0) {
    badge = { tone: 'negative', text: `Lost ${s.lost_total}` }
    if (s.removed > s.lost_total) removal = `Removed ${s.removed} · ${s.removed_but_delivered} still delivered`
  } else if (s.removed > 0) {
    badge = { tone: 'neutral', text: `Removed ${s.removed}` }
    removal = s.removed_but_delivered === s.removed ? 'all still delivered' : `${s.removed_but_delivered} still delivered`
  }
  let final: string | null = null
  const soleFinal = node.is_final_output && graph.nodes.filter((n) => n.is_final_output).length === 1
  if (soleFinal && !separateResult) {
    const top = `${totals.delivered} of ${totals.relevant} in top ${k}`
    if (badge?.tone === 'negative') final = top
    else {
      // The result replaces a neutral removal badge; the removal stays in words.
      if (badge) removal = `${badge.text} · ${removal}`
      badge = { tone: 'positive', text: top }
    }
  }
  return {
    metric,
    note: join([source ? `${s.in_top_k} in its top ${k}` : null, removal, final, ghost ? ranFor : null]),
    noteTone: final ? 'positive' : null,
    badge,
    ghost,
  }
}

/** Path mode: one document's rank at the step. `stage` undefined = the question did not run it; null = spans not loaded. */
export function pathCard(
  node: PipelineGraphNode,
  events: JourneyEvent[],
  stage: InvestigationStage | null | undefined,
  k: number | null,
  isFinal: boolean,
  finalRank: number | null,
  lossBoundary: boolean,
): CardWords {
  let badge: Badge | null = null
  let notes: Array<string | null> = []
  let tone: Tone | null = null
  let ghost = false
  const event = events.find((e) => e.kind === 'removed') ?? events.find((e) => e.kind === 'unknown') ?? events[events.length - 1]
  if (event) {
    const rank = `Rank ${event.output_rank ?? '—'}`
    if (event.kind === 'introduced') {
      badge = { tone: 'accent', text: rank }
      notes = ['Found it']
    } else if (event.kind === 'removed') {
      badge = { tone: 'negative', text: 'Removed' }
      notes = [event.reason ?? 'No reason recorded']
    } else if (event.kind === 'unknown') {
      badge = { tone: 'warning', text: 'Not recorded' }
    } else {
      const fell = lossBoundary && k != null && event.output_rank != null && event.output_rank > k
      badge = { tone: fell ? 'negative' : 'accent', text: rank }
      notes = [event.input_rank != null && event.input_rank !== event.output_rank ? `was ${event.input_rank}` : null, fell ? `fell below the top ${k}` : null]
      if (fell) tone = 'negative'
    }
  } else if (stage === undefined) {
    ghost = true
    notes = ['Not run for this question']
  } else if (stage === null) {
    notes = [node.op_type === 'SOURCE' ? "Didn't find it" : "Didn't reach it"]
  } else if (stage.status === 'SKIPPED_BY_GATE') {
    ghost = true
    notes = ['Skipped for this question']
  } else if (stage.status === 'ERROR' || stage.status === 'TIMEOUT') {
    badge = { tone: 'warning', text: statusWord(stage.status) }
  } else {
    notes = [node.op_type === 'SOURCE' ? `Not in its top ${stage.emitted}` : "Didn't reach it"]
  }
  if (isFinal) {
    notes.push(finalRank != null ? `Delivered at #${finalRank}` : 'Not delivered')
    if (finalRank != null && tone === null) tone = 'positive'
  }
  return { metric: '', note: join(notes), noteTone: tone, badge, ghost }
}

/** Question mode: candidates in and out of the step for one question. */
export function questionCard(node: PipelineGraphNode, stage: InvestigationStage | undefined): CardWords {
  if (!stage) return { metric: '', note: 'Not run for this question', noteTone: null, badge: null, ghost: true }
  const skipped = stage.status === 'SKIPPED_BY_GATE'
  const failed = stage.status === 'ERROR' || stage.status === 'TIMEOUT'
  const capture = captureWord(stage.output_capture)
  return {
    metric: `${stage.received} in · ${stage.emitted} out`,
    note: join([statusWord(stage.status), !skipped && (capture === 'Partly recorded' || capture === 'Not recorded') ? capture : null]),
    noteTone: failed ? 'warning' : null,
    badge: null,
    ghost: skipped,
  }
}

/** The result card after the only final step (left to right, when its column fits). */
export interface ResultWords {
  name: string
  /** The large number, run mode with judgments only. */
  figure: string | null
  note: string | null
  noteTone: Tone | null
}

export function resultWords(mode: 'run' | 'question' | 'path', flow: InvestigationFlow | null, k: number | null, finalRank: number | null): ResultWords {
  const name = k != null ? `Top ${k}` : 'Delivered'
  if (mode === 'path') return { name, figure: null, note: finalRank != null ? `Delivered at #${finalRank}` : 'Not delivered', noteTone: finalRank != null ? 'positive' : null }
  if (mode === 'question') return { name, figure: null, note: 'Pick a document below to follow it', noteTone: null }
  if (!flow || flow.totals.relevant === 0) return { name, figure: null, note: 'No correct answers recorded', noteTone: null }
  const { delivered, relevant } = flow.totals
  return { name, figure: `${delivered} of ${relevant}`, note: `correct delivered · ${Math.round((100 * delivered) / relevant)}%`, noteTone: null }
}
