import { InvestigateView } from '../context/dashboardQuery'
import { InvestigationDocumentRow, JourneyEvent, JourneyRow, PipelineGraph, QuerySummaryRow } from '../api'

// Pure helpers over investigation journey rows (EVIDENCE_CONTRACT sections 4–6). Nothing
// here touches the DOM or the network so every rule is unit-testable in the node environment.

export type EventKind = JourneyEvent['kind']
export type Outcome = JourneyRow['outcome']
export type ReasonEvidence = JourneyEvent['reason_evidence']

/** User-facing outcome vocabulary: text plus a glyph, never colour alone. */
export const OUTCOME_LABELS: Record<Outcome, { glyph: string; label: string }> = {
  relevant_delivered: { glyph: '✓', label: 'Relevant, delivered' },
  relevant_excluded: { glyph: '✕', label: 'Relevant, excluded' },
  retained_below_cutoff: { glyph: '↓', label: 'Retained below cutoff' },
  not_observed: { glyph: '○', label: 'Not observed in retrieval' },
  judged_nonrelevant: { glyph: '–', label: 'Judged nonrelevant' },
  unjudged: { glyph: '?', label: 'Unjudged' },
  insufficient_evidence: { glyph: '◌', label: 'Insufficient evidence' },
}

export function outcomeLabel(outcome: Outcome | string): string {
  return OUTCOME_LABELS[outcome as Outcome]?.label ?? outcome
}

export function outcomeGlyph(outcome: Outcome | string): string {
  return OUTCOME_LABELS[outcome as Outcome]?.glyph ?? '?'
}

/** Neutral glyphs for event kinds; a branch-local removal is a fact, not a verdict, so no red. */
export const KIND_GLYPHS: Record<EventKind, string> = {
  introduced: '+',
  retained: '=',
  promoted: '↑',
  demoted: '↓',
  removed: '✕',
  recovered: '↻',
  transformed: '⇢',
  unknown: '◌',
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

function bucket(row: JourneyRow): number {
  if (row.outcome === 'relevant_excluded' && row.capture_state === 'complete') return 0
  if (row.outcome === 'insufficient_evidence') return 1
  return 2
}

function byIds(a: JourneyRow, b: JourneyRow): number {
  return a.query_id.localeCompare(b.query_id) || entityKey(a).localeCompare(entityKey(b))
}

/** Default table order. Queries view: relevant misses with complete capture first, then evidence-limited
 * rows, then everything else. Documents view: by query then entity. Ties break on query_id, entity. */
export function sortForView<Row extends JourneyRow>(rows: Row[], view: InvestigateView): Row[] {
  const sorted = [...rows]
  if (view === 'queries') sorted.sort((a, b) => bucket(a) - bucket(b) || byIds(a, b))
  else sorted.sort(byIds)
  return sorted
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
    if (row.judgment === 'relevant' && (row.outcome === 'relevant_excluded' || row.outcome === 'not_observed' || row.outcome === 'retained_below_cutoff')) {
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

/** The stored summary's top loss boundaries as `op ×n`, most frequent first (ties by name), at most three. */
export function principalLossBoundaries(counts: Record<string, number>, limit = 3): string[] {
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([id, count]) => `${id} ×${count}`)
}

/** SOURCE operators that introduced the entity; without a graph every introducing operator counts. */
export function sourceLanes(row: JourneyRow, isSource?: (opId: string) => boolean): string[] {
  const lanes: string[] = []
  for (const event of row.events) {
    if (event.kind !== 'introduced' || (isSource && !isSource(event.op_id))) continue
    if (!lanes.includes(event.op_id)) lanes.push(event.op_id)
  }
  return lanes
}

/** Compact recorded transition sequence: `dense ▸ recency_filter ✕ ▸ fuse ▸ select`. Only
 * removals (✕) and uncaptured boundaries (◌) carry a glyph. */
export function transitionText(row: JourneyRow): string {
  const steps: string[] = []
  for (const event of row.events) {
    const mark = event.kind === 'removed' ? ' ✕' : event.kind === 'unknown' ? ' ◌' : ''
    const step = `${event.op_id}${mark}`
    if (steps[steps.length - 1] !== step) steps.push(step)
  }
  return steps.join(' ▸ ')
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
