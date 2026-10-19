import { InvestigationStage, JourneyEvent, JourneyRow, PipelineGraph } from '../api'
import { plural, statusWord, stepName } from './flowWords'

// One document's journey through a question in plain words: a numbered step list for its card and
// one verdict sentence for the page header, both built from the same entries. Raw event kinds stay
// in the card's "Technical details".

export type StepTone = 'accent' | 'negative' | 'warning' | 'neutral' | 'faint' | 'positive'

export interface JourneyStep {
  /** The step's op id; null for the closing delivered / not delivered entry. */
  opId: string | null
  name: string
  tone: StepTone
  text: string
  sub: string | null
}

type Kind = 'found' | 'missing' | 'moved' | 'removed' | 'recovered' | 'unknown' | 'skipped'

interface Entry {
  opId: string
  name: string
  kind: Kind
  input: number | null
  output: number | null
  reason: string | null
  stage: InvestigationStage | undefined
  boundary: boolean
}

export function ordinal(n: number): string {
  const tens = n % 100
  if (tens >= 11 && tens <= 13) return `${n}th`
  return `${n}${['th', 'st', 'nd', 'rd'][n % 10] ?? 'th'}`
}

/** Several events at one step fold into one: a removal or unknown wins, otherwise first input rank → last output rank. */
function fold(events: JourneyEvent[]): Pick<Entry, 'kind' | 'input' | 'output' | 'reason'> {
  const exit = events.find((e) => e.kind === 'removed') ?? events.find((e) => e.kind === 'unknown')
  if (exit) return { kind: exit.kind === 'removed' ? 'removed' : 'unknown', input: exit.input_rank, output: exit.output_rank, reason: exit.reason }
  const kind: Kind = events.some((e) => e.kind === 'introduced') ? 'found' : events.some((e) => e.kind === 'recovered') ? 'recovered' : 'moved'
  return { kind, input: events[0].input_rank, output: events[events.length - 1].output_rank, reason: null }
}

function entries(row: JourneyRow, graph: PipelineGraph | null, stages: InvestigationStage[] | null): Entry[] {
  const node = (id: string) => graph?.nodes.find((n) => n.node_id === id)
  const stageOf = (id: string) => stages?.find((s) => s.op_id === id)
  const isSource = (id: string) => (node(id)?.op_type ?? stageOf(id)?.op_type) === 'SOURCE'
  const nameOf = (id: string) => {
    const found = node(id)
    return found ? stepName(found).name : id
  }
  const make = (opId: string, part: Pick<Entry, 'kind' | 'input' | 'output' | 'reason'>): Entry => ({
    opId,
    name: nameOf(opId),
    ...part,
    stage: stageOf(opId),
    boundary: row.loss_boundary === opId,
  })
  const none = { input: null, output: null, reason: null }

  const byOp = new Map<string, JourneyEvent[]>()
  for (const event of row.events) byOp.set(event.op_id, [...(byOp.get(event.op_id) ?? []), event])
  const order = [...byOp.keys()]
  const visited = order.map((id) => make(id, fold(byOp.get(id)!)))
  // Sources that ran for this question but never returned it (all sources when the spans are unknown).
  const sourceIds = graph ? graph.nodes.filter((n) => n.op_type === 'SOURCE').map((n) => n.node_id) : (stages ?? []).filter((s) => s.op_type === 'SOURCE').map((s) => s.op_id)
  const silent = sourceIds
    .filter((id) => !byOp.has(id) && (stages === null || stageOf(id) !== undefined))
    .map((id) => make(id, { kind: stageOf(id)?.status === 'SKIPPED_BY_GATE' ? 'skipped' : 'missing', ...none }))
  const list = [...visited.filter((e) => isSource(e.opId)), ...silent, ...visited.filter((e) => !isSource(e.opId))]

  // Steps a gate skipped for this question, placed after the last listed step that comes before them in the pipeline.
  const position = (id: string) => {
    const index = graph ? graph.nodes.findIndex((n) => n.node_id === id) : -1
    return index >= 0 ? index : (stages ?? []).findIndex((s) => s.op_id === id)
  }
  for (const stage of stages ?? []) {
    if (stage.status !== 'SKIPPED_BY_GATE' || byOp.has(stage.op_id) || isSource(stage.op_id)) continue
    const at = position(stage.op_id)
    let index = list.length
    while (index > 0 && position(list[index - 1].opId) > at) index -= 1
    list.splice(index, 0, make(stage.op_id, { kind: 'skipped', ...none }))
  }
  return list
}

function delivered(row: JourneyRow, k: number | null): boolean {
  return row.final_membership === 'included' && row.final_rank != null && (k == null || row.final_rank <= k)
}

function fellBelow(entry: Entry, k: number | null): boolean {
  return entry.boundary && k != null && entry.output != null && entry.output > k
}

function stepOf(entry: Entry, k: number | null): JourneyStep {
  const { opId, name } = entry
  const step = (tone: StepTone, text: string, sub: string | null = null): JourneyStep => ({ opId, name, tone, text, sub })
  switch (entry.kind) {
    case 'found':
      return step(
        'accent',
        entry.output != null ? `${name} found it at rank ${entry.output}` : `${name} found it`,
        k != null && entry.output != null ? (entry.output <= k ? `In its own top ${k}` : `Outside its own top ${k}`) : null,
      )
    case 'missing': {
      const stage = entry.stage
      const sub = !stage ? 'Not returned' : stage.status === 'FIRED' ? `Not in its top ${stage.emitted}` : statusWord(stage.status)
      return step('faint', `${name} did not return it`, sub)
    }
    case 'skipped':
      return step('faint', `${name} was skipped for this question`)
    case 'removed':
      return step(entry.boundary ? 'negative' : 'neutral', `${name} removed it`, entry.reason ? `Reason: ${entry.reason}` : 'No reason recorded')
    case 'recovered':
      return step('accent', entry.output != null ? `${name} brought it back at rank ${entry.output}` : `${name} brought it back`)
    case 'unknown':
      return step('warning', `${name}: not fully recorded`, 'No reason can be given')
    default: {
      const { input, output } = entry
      const text = input != null && output != null && input !== output ? `${name} moved it ${input} → ${output}` : output != null ? `${name} kept it at rank ${output}` : `${name} kept it`
      return fellBelow(entry, k) ? step('negative', text, `Below the top ${k} cutoff`) : step('neutral', text)
    }
  }
}

/** The numbered steps of one document's journey, closing with whether it was delivered. */
export function journeySteps(row: JourneyRow, graph: PipelineGraph | null, stages: InvestigationStage[] | null, k: number | null): JourneyStep[] {
  const steps = entries(row, graph, stages).map((entry) => stepOf(entry, k))
  const final: JourneyStep = delivered(row, k)
    ? { opId: null, name: '', tone: 'positive', text: `Delivered at #${row.final_rank}`, sub: null }
    : { opId: null, name: '', tone: 'neutral', text: 'Not delivered', sub: row.final_rank != null ? `Final rank #${row.final_rank}` : null }
  return [...steps, final]
}

/** One sentence: what the searches did with the document, then the step that lost or delivered it. */
export function verdictSentence(row: JourneyRow, graph: PipelineGraph | null, stages: InvestigationStage[] | null, k: number | null): string {
  if (row.events.length === 0) return 'No search returned it.'
  const list = entries(row, graph, stages)
  const clauses: string[] = []
  for (const entry of list) {
    if (entry.kind === 'found' && !entry.boundary) clauses.push(stepOf(entry, k).text)
    if (entry.kind === 'missing') clauses.push(entry.stage?.status === 'FIRED' ? `it was not in ${entry.name}'s top ${entry.stage.emitted}` : `${entry.name} did not return it`)
  }
  const boundary = list.find((entry) => entry.boundary)
  if (boundary) {
    if (fellBelow(boundary, k)) clauses.push(`${boundary.name} placed it ${ordinal(boundary.output!)}, below the top ${k}`)
    else if (boundary.kind === 'removed') clauses.push(boundary.reason ? `${boundary.name} removed it (${boundary.reason})` : `${boundary.name} removed it`)
    else if (boundary.kind === 'unknown') clauses.push(`${boundary.name} did not record what happened to it`)
    else clauses.push(stepOf(boundary, k).text)
  } else if (delivered(row, k)) {
    const last = list.filter((entry) => entry.kind !== 'missing' && entry.kind !== 'skipped').pop()
    clauses.push(`${last ? last.name : 'The pipeline'} delivered it at #${row.final_rank}`)
  } else {
    clauses.push('it was not delivered')
  }
  const sentence = clauses.join('; ')
  return `${sentence.charAt(0).toUpperCase()}${sentence.slice(1)}.`
}

/** The document's ranks step by step, compactly: `Lexical #1 → Recency Filter removed`. A step shows
 * the best rank it output, else whether it removed the document. More than four steps keep the first three and the last. */
export function ranksTrail(row: JourneyRow, nameOf: (opId: string) => string): string {
  const byOp = new Map<string, JourneyEvent[]>()
  for (const event of row.events) byOp.set(event.op_id, [...(byOp.get(event.op_id) ?? []), event])
  const hops = [...byOp].map(([opId, events]) => {
    // A step that kept one of the document's occurrences shows its best rank, even if it removed another.
    const ranks = events.map((event) => event.output_rank).filter((rank): rank is number => rank != null)
    const name = nameOf(opId)
    if (ranks.length > 0) return `${name} #${Math.min(...ranks)}`
    if (events.some((event) => event.kind === 'removed')) return `${name} removed`
    return events.some((event) => event.kind === 'unknown') ? `${name} not recorded` : name
  })
  if (hops.length === 0) return '—'
  return (hops.length > 4 ? [...hops.slice(0, 3), '…', hops[hops.length - 1]] : hops).join(' → ')
}

/** One document over the questions it appears in: correct for how many, delivered in and missed in how many. */
export function documentSentence(rows: JourneyRow[], questions: number): string {
  const correct = new Set(rows.filter((row) => row.judgment === 'relevant').map((row) => row.query_id))
  const delivered = new Set(rows.filter((row) => row.outcome === 'relevant_delivered').map((row) => row.query_id))
  if (correct.size === 0) return `Not judged correct for any question; it appears in ${plural(questions, 'question')}.`
  return `Correct for ${plural(correct.size, 'question')}: delivered in ${delivered.size}, missed in ${correct.size - delivered.size}.`
}
