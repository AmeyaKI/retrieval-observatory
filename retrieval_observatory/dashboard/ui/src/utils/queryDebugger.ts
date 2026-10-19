import { InvestigateView } from '../context/dashboardQuery'
import { InvestigationDocumentRow, JourneyEvent, JourneyRow, PipelineGraph, QuerySummaryRow } from '../api'

// Pure helpers over investigation journey rows (EVIDENCE_CONTRACT sections 4–6). Nothing
// here touches the DOM or the network so every rule is unit-testable in the node environment.

export type EventKind = JourneyEvent['kind']
export type Outcome = JourneyRow['outcome']
export type ReasonEvidence = JourneyEvent['reason_evidence']

export type OutcomeTone = 'positive' | 'negative' | 'warning' | 'neutral'

/** User-facing outcome vocabulary: plain words plus a tone for colour (the words alone carry the meaning). */
export const OUTCOME_LABELS: Record<Outcome, { label: string; tone: OutcomeTone }> = {
  relevant_delivered: { label: 'Correct, delivered', tone: 'positive' },
  relevant_excluded: { label: 'Correct, dropped', tone: 'negative' },
  retained_below_cutoff: { label: 'Correct, ranked too low', tone: 'negative' },
  not_observed: { label: 'Correct, never found', tone: 'negative' },
  judged_nonrelevant: { label: 'Not correct', tone: 'neutral' },
  unjudged: { label: 'Not judged', tone: 'neutral' },
  insufficient_evidence: { label: 'Not enough evidence', tone: 'warning' },
}

export function outcomeLabel(outcome: Outcome | string): string {
  return OUTCOME_LABELS[outcome as Outcome]?.label ?? outcome
}

export function outcomeTone(outcome: Outcome | string): OutcomeTone {
  return OUTCOME_LABELS[outcome as Outcome]?.tone ?? 'neutral'
}

/** Ranked too low at its loss boundary although another step had it in the top k (the server's `pushed_out`). */
export function isPushedOut(row: JourneyRow, k: number | null): boolean {
  if (row.outcome !== 'retained_below_cutoff' || k == null) return false
  return row.events.some((event) => event.op_id !== row.loss_boundary && event.output_present && event.output_rank != null && event.output_rank <= k)
}

export function outcomeText(row: JourneyRow, k: number | null): string {
  return isPushedOut(row, k) ? `Correct, pushed out of the top ${k}` : outcomeLabel(row.outcome)
}

export function judgedText(row: JourneyRow): string {
  if (row.judgment === 'relevant') return row.grade != null && row.grade > 1 ? `Correct · grade ${row.grade}` : 'Correct'
  return row.judgment === 'nonrelevant' ? 'Not correct' : 'Not judged'
}

/** Where the document entered: `dense #5 · bm25 #37`, best rank first; without `isSource` every introducing step counts. */
export function cameFrom(row: JourneyRow, isSource?: (opId: string) => boolean): string {
  const found = new Map<string, number | null>()
  for (const event of row.events) {
    if (event.kind === 'introduced' && (!isSource || isSource(event.op_id)) && !found.has(event.op_id)) found.set(event.op_id, event.output_rank)
  }
  if (found.size === 0) return '—'
  return [...found]
    .sort((a, b) => (a[1] ?? Infinity) - (b[1] ?? Infinity))
    .map(([opId, rank]) => (rank != null ? `${opId} #${rank}` : opId))
    .join(' · ')
}

/** The id a person reads: the namespace only when the scope has more than one. */
export function displayEntity(row: Pick<JourneyRow, 'namespace' | 'entity_id'>, singleNamespace: boolean): string {
  return singleNamespace ? row.entity_id : `${row.namespace}:${row.entity_id}`
}

/** `namespace:entity_id` (a document summary's `entity`, the URL's `entity`) split at its first colon. */
export function splitEntity(entity: string): Pick<JourneyRow, 'namespace' | 'entity_id'> {
  const at = entity.indexOf(':')
  return at < 0 ? { namespace: '', entity_id: entity } : { namespace: entity.slice(0, at), entity_id: entity.slice(at + 1) }
}

export function evidenceLabel(evidence: ReasonEvidence | string | null | undefined): 'recorded' | 'inferred' | 'unavailable' {
  if (evidence === 'recorded') return 'recorded'
  if (evidence === 'inferred' || evidence === 'legacy_inferred') return 'inferred'
  return 'unavailable'
}

export function entityKey(row: JourneyRow): string {
  return `${row.namespace}:${row.entity_id}`
}

export interface PathHighlight {
  /** Operator nodes the entity passed through, in event order, de-duplicated. */
  nodeIds: string[]
  edges: [string, string][]
  kinds: Record<string, EventKind>
  /** Operators whose boundary was not fully captured for this entity. */
  incomplete: string[]
}

/** The path of one journey through the graph. With a graph, an edge is drawn from every earlier
 * path node that the graph names as a parent (so fan-in shows both lanes); without one, consecutive
 * event operators are joined. A later `removed`/`unknown` event at an operator wins over an
 * earlier kind at the same operator. */
export function pathHighlight(row: JourneyRow, graph?: PipelineGraph | null): PathHighlight {
  const nodeIds: string[] = []
  const kinds: Record<string, EventKind> = {}
  const incomplete: string[] = []
  for (const event of row.events) {
    if (!(event.op_id in kinds)) nodeIds.push(event.op_id)
    if (!(event.op_id in kinds) || event.kind === 'removed' || event.kind === 'unknown') kinds[event.op_id] = event.kind
    if ((event.kind === 'unknown' || !event.boundary_complete) && !incomplete.includes(event.op_id)) incomplete.push(event.op_id)
  }
  const edges: [string, string][] = []
  if (graph) {
    const parents = new Map<string, string[]>()
    for (const edge of graph.edges) parents.set(edge.target, [...(parents.get(edge.target) ?? []), edge.source])
    nodeIds.forEach((id, index) => {
      const earlier = nodeIds.slice(0, index)
      for (const parent of parents.get(id) ?? []) if (earlier.includes(parent)) edges.push([parent, id])
    })
  } else {
    for (let index = 1; index < nodeIds.length; index += 1) edges.push([nodeIds[index - 1], nodeIds[index]])
  }
  return { nodeIds, edges, kinds, incomplete }
}

/** Rows that exited (or crossed an incomplete boundary) at the stage, plus rows whose final loss
 * boundary is that stage. A null stage keeps every row. */
export function stageFilter<Row extends JourneyRow>(rows: Row[], stageId: string | null | undefined): Row[] {
  if (!stageId) return rows
  return rows.filter(
    (row) => row.loss_boundary === stageId || row.events.some((event) => event.op_id === stageId && (event.kind === 'removed' || event.kind === 'unknown')),
  )
}

/** A relevant entity the final output does not deliver (the misses the rollup counts). */
function isRelevantMiss(row: JourneyRow): boolean {
  return row.judgment === 'relevant' && (row.outcome === 'relevant_excluded' || row.outcome === 'not_observed' || row.outcome === 'retained_below_cutoff')
}

function bucket(row: JourneyRow): number {
  if (isRelevantMiss(row) && row.capture_state === 'complete') return 0
  if (row.outcome === 'insufficient_evidence' || isRelevantMiss(row)) return 1
  if (row.outcome === 'relevant_delivered') return 2
  return 3
}

function byIds(a: JourneyRow, b: JourneyRow): number {
  return a.query_id.localeCompare(b.query_id) || entityKey(a).localeCompare(entityKey(b))
}

/** Final rank ascending; rows without one last. */
function byRank(a: JourneyRow, b: JourneyRow): number {
  return (a.final_rank ?? Infinity) - (b.final_rank ?? Infinity)
}

/** Default table order. Queries view: relevant misses with complete capture first (removed, never
 * observed, or retained below the cutoff), then evidence-limited rows, then delivered relevant rows,
 * then every other row by final rank (rows without one last). Documents view: by query then entity.
 * Ties break on query_id, entity. */
export function sortForView<Row extends JourneyRow>(rows: Row[], view: InvestigateView): Row[] {
  const sorted = [...rows]
  if (view === 'queries') sorted.sort((a, b) => bucket(a) - bucket(b) || (bucket(a) === 3 ? byRank(a, b) : 0) || byIds(a, b))
  else sorted.sort(byIds)
  return sorted
}

/** The document a question page follows: the URL's entity, else the first correct document it
 * missed (table order), else its first correct document, else none. */
export function focusRowFor<Row extends JourneyRow>(rows: Row[], entity: string | null, trace: string | null): Row | null {
  if (entity) {
    const selected = rows.find((row) => entityKey(row) === entity && (!trace || row.trace_id === trace))
    if (selected) return selected
  }
  const ordered = sortForView(rows, 'queries')
  return ordered.find(isRelevantMiss) ?? ordered.find((row) => row.judgment === 'relevant') ?? null
}

/** Roving-focus rule for table rows; null when the key is not a navigation key. */
export function nextIndexForKey(key: string, index: number, length: number): number | null {
  if (length <= 0) return null
  switch (key) {
    case 'ArrowDown':
      return Math.min(index + 1, length - 1)
    case 'ArrowUp':
      return Math.max(index - 1, 0)
    case 'Home':
      return 0
    case 'End':
      return length - 1
    default:
      return null
  }
}

export interface QueryRollup {
  query_id: string
  trace_ids: string[]
  rows: number
  relevant_delivered: number
  relevant_missed: number
  unjudged_included: number
  unknown_capture: number
  /** Final loss boundaries of the query's excluded relevant entities, most frequent first. */
  boundaries: string[]
}

/** Per-query counts aggregated from the loaded rows (the list envelope strips `by_query`). */
export function queryRollups(rows: JourneyRow[]): QueryRollup[] {
  const byQuery = new Map<string, QueryRollup & { boundaryCounts: Record<string, number> }>()
  for (const row of rows) {
    const rollup =
      byQuery.get(row.query_id) ??
      { query_id: row.query_id, trace_ids: [], rows: 0, relevant_delivered: 0, relevant_missed: 0, unjudged_included: 0, unknown_capture: 0, boundaries: [], boundaryCounts: {} }
    rollup.rows += 1
    if (!rollup.trace_ids.includes(row.trace_id)) rollup.trace_ids.push(row.trace_id)
    if (row.outcome === 'relevant_delivered') rollup.relevant_delivered += 1
    if (isRelevantMiss(row)) {
      rollup.relevant_missed += 1
      if (row.loss_boundary) rollup.boundaryCounts[row.loss_boundary] = (rollup.boundaryCounts[row.loss_boundary] ?? 0) + 1
    }
    if (row.judgment === 'unjudged' && row.final_membership === 'included') rollup.unjudged_included += 1
    if (row.outcome === 'insufficient_evidence' || row.capture_state === 'partial') rollup.unknown_capture += 1
    byQuery.set(row.query_id, rollup)
  }
  return [...byQuery.values()].map(({ boundaryCounts, ...rollup }) => ({
    ...rollup,
    boundaries: Object.entries(boundaryCounts)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([id]) => id),
  }))
}

/** Content preview from a row or event payload, when the projection captured any. */
export function contentPreview(row: JourneyRow): string | null {
  const sources = [row.metadata, ...row.events.map((event) => event.metadata)]
  for (const meta of sources) {
    if (!meta) continue
    for (const key of ['preview', 'title', 'text']) {
      const value = meta[key]
      if (typeof value === 'string' && value.trim()) return value
    }
  }
  return null
}

export function isJourneyRow(row: JourneyRow | InvestigationDocumentRow | QuerySummaryRow): row is JourneyRow {
  return 'entity_id' in row
}

export function isQuerySummaryRow(row: JourneyRow | InvestigationDocumentRow | QuerySummaryRow): row is QuerySummaryRow {
  return 'loss_boundaries' in row
}
