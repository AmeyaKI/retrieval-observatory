import { TraceOperatorSpan } from '../api'

export interface ReplayStep {
  level: number
  spans: TraceOperatorSpan[]
}

/** Groups spans into replay steps by dependency depth (0 = no parents), so parallel arms
 * of a fusion pipeline land in the same step instead of being serialized by array order. */
export function buildReplaySteps(spans: TraceOperatorSpan[]): ReplayStep[] {
  const byId = new Map(spans.map((s) => [s.op_id, s]))
  const levelCache = new Map<string, number>()

  function levelOf(span: TraceOperatorSpan, seen: Set<string>): number {
    const cached = levelCache.get(span.op_id)
    if (cached !== undefined) return cached
    if (seen.has(span.op_id)) return 0 // cycle guard, shouldn't happen in a valid trace
    seen.add(span.op_id)
    const parents = span.parent_ids.map((id) => byId.get(id)).filter((s): s is TraceOperatorSpan => !!s)
    const level = parents.length === 0 ? 0 : 1 + Math.max(...parents.map((p) => levelOf(p, seen)))
    levelCache.set(span.op_id, level)
    return level
  }

  for (const span of spans) levelOf(span, new Set())

  const byLevel = new Map<number, TraceOperatorSpan[]>()
  for (const span of spans) {
    const level = levelCache.get(span.op_id) ?? 0
    byLevel.set(level, [...(byLevel.get(level) ?? []), span])
  }

  return Array.from(byLevel.entries())
    .sort(([a], [b]) => a - b)
    .map(([level, stepSpans]) => ({ level, spans: stepSpans }))
}

export interface CandidateDiffEntry {
  doc_id: string
  status: 'appeared' | 'disappeared' | 'rank_changed' | 'unchanged'
  rank: number | null
  prevRank: number | null
}

/** Diffs the candidate set as of one replay step against the previous step. "As of a step"
 * is the union of every span-in-that-step's outputs (FIRED spans only). */
export function diffStep(prevOutputs: Map<string, number>, currOutputs: Map<string, number>): CandidateDiffEntry[] {
  const ids = new Set([...prevOutputs.keys(), ...currOutputs.keys()])
  const out: CandidateDiffEntry[] = []
  for (const id of ids) {
    const prevRank = prevOutputs.has(id) ? prevOutputs.get(id)! : null
    const rank = currOutputs.has(id) ? currOutputs.get(id)! : null
    let status: CandidateDiffEntry['status']
    if (prevRank === null && rank !== null) status = 'appeared'
    else if (prevRank !== null && rank === null) status = 'disappeared'
    else if (prevRank !== rank) status = 'rank_changed'
    else status = 'unchanged'
    out.push({ doc_id: id, status, rank, prevRank })
  }
  return out.sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999))
}

export function spanOutputs(span: TraceOperatorSpan): Map<string, number> {
  const m = new Map<string, number>()
  if (span.status !== 'FIRED') return m
  for (const doc of span.outputs) m.set(doc.doc_id, doc.rank)
  return m
}

export function stepOutputs(step: ReplayStep): Map<string, number> {
  const m = new Map<string, number>()
  for (const span of step.spans) {
    if (span.status !== 'FIRED') continue
    for (const doc of span.outputs) {
      m.set(doc.doc_id, doc.rank)
    }
  }
  return m
}

/** Doc IDs seen anywhere in the trace's outputs that are absent from the last replay step
 * -- i.e. candidates that were dropped somewhere along the way. Lets the query timeline
 * surface a "dropped candidates" list without the user typing doc_ids by hand. */
export function droppedDocIds(spans: TraceOperatorSpan[]): string[] {
  const steps = buildReplaySteps(spans)
  if (steps.length === 0) return []
  const everSeen = new Set<string>()
  for (const step of steps) {
    for (const [id] of stepOutputs(step)) everSeen.add(id)
  }
  const final = stepOutputs(steps[steps.length - 1])
  return Array.from(everSeen).filter((id) => !final.has(id))
}
