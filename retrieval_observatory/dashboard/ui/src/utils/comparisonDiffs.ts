import { OperatorAttributionRow, Recommendation } from '../api'

export function bestRowsByOp(rows: OperatorAttributionRow[]): Map<string, OperatorAttributionRow> {
  const m = new Map<string, OperatorAttributionRow>()
  for (const row of rows) {
    const existing = m.get(row.op_id)
    if (!existing || row.n_pairs > existing.n_pairs) m.set(row.op_id, row)
  }
  return m
}

export interface AttributionFlip {
  opId: string
  a: OperatorAttributionRow
  b: OperatorAttributionRow
  reason: 'direction_flipped' | 'significance_changed'
}

/** Item D.3: operators present in both runs whose marginal-contribution direction flipped
 * sign or whose significance flag changed -- the two changes worth a human's attention. */
export function diffAttribution(rowsA: OperatorAttributionRow[], rowsB: OperatorAttributionRow[]): AttributionFlip[] {
  const byOpA = bestRowsByOp(rowsA)
  const byOpB = bestRowsByOp(rowsB)
  const commonOps = Array.from(byOpA.keys()).filter((id) => byOpB.has(id))
  const flips: AttributionFlip[] = []
  for (const opId of commonOps) {
    const a = byOpA.get(opId)!
    const b = byOpB.get(opId)!
    const signFlip = a.delta != null && b.delta != null && a.delta !== 0 && b.delta !== 0 && Math.sign(a.delta) !== Math.sign(b.delta)
    const sigChange = Boolean(a.significant) !== Boolean(b.significant)
    if (signFlip) flips.push({ opId, a, b, reason: 'direction_flipped' })
    else if (sigChange) flips.push({ opId, a, b, reason: 'significance_changed' })
  }
  return flips
}

export interface RecommendationDiff {
  newRecs: Recommendation[]
  resolvedRecs: Recommendation[]
  persisting: Recommendation[]
}

/** Item D.4: diff two runs' Findings recommendations by action string. */
export function diffRecommendations(recsA: Recommendation[], recsB: Recommendation[]): RecommendationDiff {
  const actionsA = new Set(recsA.map((r) => r.action))
  const actionsB = new Set(recsB.map((r) => r.action))
  return {
    newRecs: recsA.filter((r) => !actionsB.has(r.action)),
    resolvedRecs: recsB.filter((r) => !actionsA.has(r.action)),
    persisting: recsA.filter((r) => actionsB.has(r.action)),
  }
}
