import { FlowMiss, FlowStep, InvestigationFlow, InvestigationStage, JourneyEvent, PipelineGraph, PipelineGraphNode, StageSummary } from '../api'
import { collapsedNodeId } from './dagLayout'
import { outcomeLabel } from './queryDebugger'

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
  /** The note in full for the card's title tooltip, when the card shows a shorter one. */
  fullNote?: string | null
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

/** Collapsed: `op#N` step counts, co-presence pairs (self-pairs dropped) and the misses' steps fold onto `op`. */
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
  const fold = (id: string | null) => (id === null ? null : collapsedNodeId(id))
  const misses = flow.misses.map((miss) => ({ ...miss, loss_boundary: fold(miss.loss_boundary), best_op: fold(miss.best_op) }))
  return { ...flow, steps, copresence, misses }
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

/** What one step did with the document, from all its events there (several chunks, folded invocations). */
export interface FoldedStep {
  /** found / recovered: the document entered here (no event had it in its input); moved: kept it. */
  kind: 'found' | 'recovered' | 'moved' | 'removed' | 'unknown'
  /** Best (lowest) input rank of any of its occurrences. */
  input: number | null
  /** Best output rank of the occurrences it kept. */
  output: number | null
  /** The removal (or unknown) reason when it did not keep the document. */
  reason: string | null
  /** It kept the document but removed another occurrence: the words for that removal. */
  also: string | null
}

const best = (ranks: Array<number | null>): number | null => {
  const known = ranks.filter((rank): rank is number => rank != null)
  return known.length > 0 ? Math.min(...known) : null
}

/** The one fold rule for several events at one step. Any occurrence in its output means the step
 * kept the document, at the best output rank among them; an occurrence output and then removed (a
 * folded op#2) does not count. Removal or unknown wins only when no occurrence was kept. Found /
 * brought back only when no event had the document in its input. */
export function foldStep(events: JourneyEvent[]): FoldedStep {
  const removed = events.filter((e) => e.kind === 'removed')
  const gone = new Set(removed.map((e) => e.occurrence_entity_id))
  const kept = events.filter((e) => e.kind !== 'removed' && e.output_present && !gone.has(e.occurrence_entity_id))
  if (kept.length === 0) {
    const exit = removed[0] ?? events.find((e) => e.kind === 'unknown')
    if (exit) return { kind: exit.kind === 'removed' ? 'removed' : 'unknown', input: exit.input_rank, output: exit.output_rank, reason: exit.reason, also: null }
  }
  const passed = kept.length > 0 ? kept : events
  const entered = !events.some((e) => e.input_present)
  const kind = entered && passed.some((e) => e.kind === 'introduced') ? 'found' : entered && passed.some((e) => e.kind === 'recovered') ? 'recovered' : 'moved'
  const duplicate = removed.every((e) => e.reason_evidence === 'recorded' && /dup/i.test(e.reason ?? ''))
  return {
    kind,
    input: best(events.map((e) => e.input_rank)),
    output: best(passed.map((e) => e.output_rank)),
    reason: null,
    also: removed.length > 0 && kept.length > 0 ? (duplicate ? 'Removed a duplicate occurrence' : 'Kept another occurrence') : null,
  }
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
  let shown = removal
  const soleFinal = node.is_final_output && graph.nodes.filter((n) => n.is_final_output).length === 1
  if (soleFinal && !separateResult) {
    const top = `${totals.delivered} of ${totals.relevant} in top ${k}`
    if (badge?.tone === 'negative') final = top
    else {
      // The result replaces a neutral removal badge; the removal stays in the title and the step panel.
      if (badge) removal = `${badge.text} · ${removal}`
      shown = null
      badge = { tone: 'positive', text: top }
    }
  }
  const notes = (removed: string | null) => join([source ? `${s.in_top_k} in its top ${k}` : null, removed, final, ghost ? ranFor : null])
  const words: CardWords = { metric, note: notes(shown), noteTone: final ? 'positive' : null, badge, ghost }
  if (shown !== removal) words.fullNote = notes(removal)
  return words
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
  let fell = false
  const step = events.length > 0 ? foldStep(events) : null
  if (step) {
    const rank = `Rank ${step.output ?? '—'}`
    if (step.kind === 'found') {
      badge = { tone: 'accent', text: rank }
      notes = ['Found it', step.also]
    } else if (step.kind === 'removed') {
      badge = { tone: 'negative', text: 'Removed' }
      notes = [step.reason ?? 'No reason recorded']
    } else if (step.kind === 'unknown') {
      badge = { tone: 'warning', text: 'Not recorded' }
    } else {
      fell = lossBoundary && k != null && step.output != null && step.output > k
      badge = { tone: fell ? 'negative' : 'accent', text: rank }
      notes = [step.input != null && step.input !== step.output ? `was ${step.input}` : null, step.also, fell ? `fell below the top ${k}` : null]
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
  const delivery = finalRank != null ? `Delivered at #${finalRank}` : 'Not delivered'
  if (isFinal) {
    notes.push(delivery)
    if (finalRank != null && tone === null) tone = 'positive'
  }
  // A card holds two short lines; the title keeps every word. It says "below top k", and the final
  // card keeps its delivery: a kept occurrence, and "Not delivered" after "below top k", go to the title.
  const shown = notes
    .filter((note) => !(isFinal && ((step?.also && note === step.also) || (fell && note === delivery))))
    .map((note) => (fell && note === `fell below the top ${k}` ? `below top ${k}` : note))
  const words: CardWords = { metric: '', note: join(shown), noteTone: tone, badge, ghost }
  if (join(shown) !== join(notes)) words.fullNote = join(notes)
  return words
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

// ── The run's headline and its questions that missed a correct document ─────────────────────

function was(n: number): string {
  return n === 1 ? 'was' : 'were'
}

function listNames(names: string[]): string {
  return names.length <= 1 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/** The page's headline and its lede sentences; `lost` is the part of the headline to show as lost. */
export interface RunHeadlineWords {
  headline: string
  lede: string[]
  lost: string | null
}

/** Whether the worst step's lost documents were in the top k at an earlier step (a misses' best rank within k). */
function earlierSentence(n: number, before: number, name: string, k: number): string {
  if (n === 1) return before === 1 ? `The one lost at ${name} was in the top ${k} at an earlier step.` : `The one lost at ${name} was not in the top ${k} at any earlier step.`
  if (before === 0) return `None of the ${n} lost at ${name} was in the top ${k} at an earlier step.`
  if (before === n) return `All ${n} lost at ${name} were in the top ${k} at an earlier step.`
  return `Of the ${n} lost at ${name}, ${before} ${was(before)} in the top ${k} at an earlier step; ${n - before} never ${was(n - before)}.`
}

/** Which step loses the most correct documents, in one sentence, then the run's result. Pass the
 * flow folded like the diagram (its steps and misses name the same ids). */
export function runHeadline(flow: InvestigationFlow, graph: PipelineGraph | null): RunHeadlineWords {
  const { k, totals } = flow
  if (totals.relevant === 0) return { headline: "This run has no correct answers recorded, so losses can't be counted.", lede: [], lost: null }
  const order = (id: string) => {
    const index = graph?.nodes.findIndex((n) => n.node_id === id) ?? -1
    return index < 0 ? Infinity : index
  }
  const nameOf = (id: string) => {
    const node = graph?.nodes.find((n) => n.node_id === id)
    return node ? stepName(node).name : id
  }
  const most = Math.max(0, ...Object.values(flow.steps).map((step) => step.lost_total))
  const worst = most > 0 ? Object.keys(flow.steps).filter((id) => flow.steps[id].lost_total === most).sort((a, b) => order(a) - order(b) || a.localeCompare(b)) : []
  const pct = Math.round((100 * totals.delivered) / totals.relevant)
  const lede = [`${totals.delivered} of ${plural(totals.relevant, 'correct document')} (${pct}%) reached the top ${k} across ${plural(totals.questions, 'question')}.`]
  const never = `${totals.never_found} ${was(totals.never_found)} never found by any search.`
  const partial = `${totals.insufficient} could not be traced fully.`
  if (totals.missed === 0) return { headline: `All ${plural(totals.relevant, 'correct document')} reached the top ${k}.`, lede, lost: null }
  if (worst.length === 0) {
    const headline = totals.never_found > 0 ? `No step lost a correct document; ${never}` : `No step lost a correct document; ${totals.missed} could not be traced fully.`
    if (totals.never_found > 0 && totals.insufficient > 0) lede.push(partial)
    return { headline, lede, lost: null }
  }
  const lost = `${most} of the ${totals.missed}`
  let headline: string
  if (worst.length === 1) {
    const name = nameOf(worst[0])
    headline = `${name} loses the most correct documents: ${lost} that missed the top ${k}.`
    const here = flow.misses.filter((miss) => miss.loss_boundary === worst[0] && (miss.outcome === 'relevant_excluded' || miss.outcome === 'retained_below_cutoff'))
    const before = Math.min(most, here.filter((miss) => miss.best_rank != null && miss.best_rank <= k).length)
    lede.push(earlierSentence(most, before, name, k))
  } else {
    headline = `${listNames(worst.map(nameOf))} each lose ${lost} correct documents that missed the top ${k}.`
  }
  if (totals.never_found > 0) lede.push(never)
  if (totals.insufficient > 0) lede.push(partial)
  return { headline, lede, lost }
}

/** One question's missed correct documents, in the server's order (questions that got none first). */
export interface MissedQuestion {
  query_id: string
  query_text: string | null
  /** The question's trace when all its misses share one. */
  trace_id: string | null
  misses: FlowMiss[]
  /** The question's correct documents, and how many of them it delivered. */
  relevant: number
  delivered: number
}

export function missedQuestions(flow: InvestigationFlow): MissedQuestion[] {
  const byQuery = new Map<string, FlowMiss[]>()
  for (const miss of flow.misses) byQuery.set(miss.query_id, [...(byQuery.get(miss.query_id) ?? []), miss])
  return [...byQuery].map(([query_id, misses]) => ({
    query_id,
    query_text: misses.find((miss) => miss.query_text)?.query_text ?? null,
    trace_id: new Set(misses.map((miss) => miss.trace_id)).size === 1 ? misses[0].trace_id : null,
    misses,
    relevant: misses[0].question_relevant,
    delivered: misses[0].question_delivered,
  }))
}

/** Questions with a miss lost at `stage` and with a miss of `outcome`; null keeps every question. */
export function filterMissed(questions: MissedQuestion[], filters: { stage?: string | null; outcome?: string | null }): MissedQuestion[] {
  const { stage, outcome } = filters
  return questions.filter((q) => (!stage || q.misses.some((miss) => miss.loss_boundary === stage)) && (!outcome || q.misses.some((miss) => miss.outcome === outcome)))
}

export interface ReasonChip {
  outcome: string
  label: string
  /** Questions with at least one miss of this outcome. */
  questions: number
}

/** The reason filters over the missed list: questions per reason; the first also counts the documents pushed out. */
export function reasonChips(questions: MissedQuestion[]): ReasonChip[] {
  const count = (outcome: string) => filterMissed(questions, { outcome }).length
  const pushed = questions.reduce((sum, q) => sum + q.misses.filter((miss) => miss.outcome === 'retained_below_cutoff' && miss.pushed_out).length, 0)
  const low = count('retained_below_cutoff')
  const chips: ReasonChip[] = [
    { outcome: 'retained_below_cutoff', label: `Ranked too low or pushed out · ${low} (${pushed} pushed out)`, questions: low },
    { outcome: 'relevant_excluded', label: `Dropped · ${count('relevant_excluded')}`, questions: count('relevant_excluded') },
    { outcome: 'not_observed', label: `Never found · ${count('not_observed')}`, questions: count('not_observed') },
  ]
  const unknown = count('insufficient_evidence')
  if (unknown > 0) chips.push({ outcome: 'insufficient_evidence', label: `Not enough evidence · ${unknown}`, questions: unknown })
  return chips
}

/** What happened to one missed correct document, with the step that ranked it best when the line does not say so. */
export function missLine(miss: FlowMiss, k: number | null, nameOf: (opId: string) => string): { text: string; sub: string | null } {
  const step = miss.loss_boundary && miss.loss_boundary !== 'not_observed' && miss.loss_boundary !== 'unknown' ? nameOf(miss.loss_boundary) : null
  const at = (word: string) => (step ? ` ${word} ${step}` : '')
  const final = miss.final_rank != null ? `#${miss.final_rank}` : null
  let text: string
  let showsBest = false
  if (miss.outcome === 'retained_below_cutoff' && miss.pushed_out && miss.best_rank != null) {
    text = `${k != null ? `Pushed out of the top ${k}` : 'Pushed out'}${at('by')} · #${miss.best_rank}${final ? ` → ${final}` : ''}`
    showsBest = true
  } else if (miss.outcome === 'retained_below_cutoff') text = `Ranked too low${at('at')}${final ? ` · ${final}` : ''}`
  else if (miss.outcome === 'relevant_excluded') text = step ? `Dropped by ${step}` : 'Dropped'
  else if (miss.outcome === 'not_observed') text = 'Never found by any search'
  else if (miss.outcome === 'insufficient_evidence') text = `Not enough evidence${at('at')}`
  else text = outcomeLabel(miss.outcome)
  const sub = !showsBest && miss.best_rank != null && miss.best_op && miss.best_op !== miss.loss_boundary ? `${nameOf(miss.best_op)} had it at #${miss.best_rank}` : null
  return { text, sub }
}
