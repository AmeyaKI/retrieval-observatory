import { PipelineGraph, PipelineGraphEdge, PipelineGraphNode } from '../api'

// Pure, dependency-free layout for the Investigate pipeline diagram. Columns place every step as
// late as possible (parallel lanes line up before their merge), rows keep lanes apart, a step in
// the straight line of a long edge is lifted off it, and the diagram runs left to right when it
// fits the container and top to bottom otherwise.

export const CARD_MIN_W = 132
export const CARD_MAX_W = 240
/** Kind, name, id, metric and two lines of badge and note. */
export const CARD_H = 126
export const GAP_MIN = 20
export const GAP_MAX = 140
export const PAD = 12
/** Left to right: space between two cards of one column. */
export const ROW_GAP = 32
/** Top to bottom: space between levels, room for an edge label. */
export const LEVEL_GAP = 40
/** A container narrower than this (a phone) always gets the top-to-bottom diagram. */
export const PHONE_W = 480

export type Orientation = 'horizontal' | 'vertical'

export interface FlowNode extends PipelineGraphNode {
  x: number
  y: number
  w: number
  h: number
  col: number
  row: number
}

export interface FlowEdge {
  source: string
  target: string
  kind: PipelineGraphEdge['kind']
  conditional: boolean
  path: string
  /** The curve's point at t = 0.5, for labels. */
  mid: { x: number; y: number }
}

/** The result card after the only final step, in its own last column (left to right only). */
export interface FlowResult {
  x: number
  y: number
  w: number
  h: number
  /** From the final step to the result card. */
  edge: FlowEdge
}

export interface FlowLayout {
  orientation: Orientation
  nodes: FlowNode[]
  edges: FlowEdge[]
  /** Null when the graph has several final steps, or the extra column does not fit. */
  result: FlowResult | null
  width: number
  height: number
  /** Top to bottom only: the lanes do not fit the width, so the diagram container scrolls sideways. */
  overflowX: boolean
}

const RESULT_ID = '\u0000result'

const byId = (a: string, b: string) => a.localeCompare(b)

/** Kahn's order; nodes left over by a cycle follow in id order so the layout never loops. */
function topoOrder(ids: string[], parents: Map<string, string[]>, children: Map<string, string[]>): string[] {
  const indegree = new Map(ids.map((id) => [id, parents.get(id)!.length]))
  const queue = ids.filter((id) => indegree.get(id) === 0).sort(byId)
  const order: string[] = []
  while (queue.length > 0) {
    const id = queue.shift()!
    order.push(id)
    for (const child of children.get(id)!) {
      indegree.set(child, indegree.get(child)! - 1)
      if (indegree.get(child) === 0) queue.push(child)
    }
  }
  const placed = new Set(order)
  return [...order, ...ids.filter((id) => !placed.has(id)).sort(byId)]
}

function columnsOf(ids: string[], parents: Map<string, string[]>, children: Map<string, string[]>): Map<string, number> {
  const order = topoOrder(ids, parents, children)
  const depth = new Map<string, number>()
  for (const id of order) depth.set(id, Math.max(-1, ...parents.get(id)!.map((p) => depth.get(p) ?? 0)) + 1)
  const maxDepth = Math.max(0, ...depth.values())
  const col = new Map<string, number>()
  for (const id of [...order].reverse()) {
    if (parents.get(id)!.length === 0) col.set(id, 0)
    else if (children.get(id)!.length === 0) col.set(id, maxDepth)
    else col.set(id, Math.min(...children.get(id)!.map((c) => col.get(c) ?? maxDepth)) - 1)
  }
  return col
}

function rowsOf(ids: string[], parents: Map<string, string[]>, col: Map<string, number>, edges: Array<[string, string]>): Map<string, number> {
  const row = new Map<string, number>()
  const maxCol = Math.max(0, ...col.values())
  const inColumn = (c: number) => ids.filter((id) => col.get(id) === c)
  for (let c = 0; c <= maxCol; c += 1) {
    const desired = inColumn(c).map((id) => {
      const placed = parents.get(id)!.filter((p) => row.has(p))
      const want = placed.length > 0 ? placed.reduce((sum, p) => sum + row.get(p)!, 0) / placed.length : 0
      return { id, want }
    })
    // Sources keep id order; later columns follow their parents.
    desired.sort((a, b) => (c === 0 ? byId(a.id, b.id) : a.want - b.want || byId(a.id, b.id)))
    desired.forEach((item, index) => {
      const want = c === 0 ? index : item.want
      row.set(item.id, index === 0 ? want : Math.max(want, row.get(desired[index - 1].id)! + 1))
    })
  }

  // Move a step that sits in the straight line of an edge spanning more than one column: first onto
  // the nearest existing lane outside the line's band (ties to the upper one), else a row beside it.
  const collides = (r: number, line: number) => Math.abs(r - line) < 0.5
  const spaced = (id: string, candidate: number) => inColumn(col.get(id)!).every((other) => other === id || Math.abs(row.get(other)! - candidate) >= 1)
  for (let pass = 0; pass < 2 * ids.length + 2; pass += 1) {
    let moved = false
    for (const [source, target] of edges) {
      const cs = col.get(source)!
      const ct = col.get(target)!
      for (let c = cs + 1; c < ct; c += 1) {
        const line = row.get(source)! + ((row.get(target)! - row.get(source)!) * (c - cs)) / (ct - cs)
        for (const id of inColumn(c)) {
          if (!collides(row.get(id)!, line)) continue
          const lanes = Number.isInteger(line) ? [] : [Math.floor(line), Math.ceil(line)].sort((a, b) => Math.abs(a - line) - Math.abs(b - line) || a - b)
          const beside = Array.from({ length: ids.length + 1 }, (_, i) => [line - (i + 1), line + (i + 1)]).flat()
          const next = [...lanes, ...beside].find((candidate) => !collides(candidate, line) && spaced(id, candidate))
          if (next !== undefined) {
            row.set(id, next)
            moved = true
          }
        }
      }
    }
    if (!moved) break
  }
  const minRow = ids.length > 0 ? Math.min(...row.values()) : 0
  for (const id of ids) row.set(id, row.get(id)! - minRow)
  return row
}

/** Card width and gap stretched linearly from the minimum toward the maximum to fill `available`. */
function stretch(count: number, available: number): { w: number; gap: number } {
  const gaps = Math.max(0, count - 1)
  const base = count * CARD_MIN_W + gaps * GAP_MIN
  const slope = count * (CARD_MAX_W - CARD_MIN_W) + gaps * (GAP_MAX - GAP_MIN)
  const t = slope > 0 ? Math.min(1, Math.max(0, (available - base) / slope)) : 0
  return { w: Math.floor(CARD_MIN_W + t * (CARD_MAX_W - CARD_MIN_W)), gap: Math.floor(GAP_MIN + t * (GAP_MAX - GAP_MIN)) }
}

/** Attach offsets over the middle 60 % of a side, one slot per edge, in the given order. */
function spread(count: number, index: number): number {
  return count <= 1 ? 0.5 : 0.2 + (0.6 * (index + 0.5)) / count
}

export function layoutFlow(graph: PipelineGraph, opts: { width: number; orientation?: 'auto' | Orientation }): FlowLayout {
  const ids = graph.nodes.map((node) => node.node_id)
  const known = new Set(ids)
  const graphEdges = graph.edges.filter((edge) => known.has(edge.source) && known.has(edge.target) && edge.source !== edge.target)
  const parents = new Map(ids.map((id) => [id, [] as string[]]))
  const children = new Map(ids.map((id) => [id, [] as string[]]))
  for (const edge of graphEdges) {
    if (!parents.get(edge.target)!.includes(edge.source)) parents.get(edge.target)!.push(edge.source)
    if (!children.get(edge.source)!.includes(edge.target)) children.get(edge.source)!.push(edge.target)
  }
  const col = columnsOf(ids, parents, children)
  const row = rowsOf(
    ids,
    parents,
    col,
    graphEdges.map((edge) => [edge.source, edge.target]),
  )
  const cols = ids.length > 0 ? Math.max(...col.values()) + 1 : 0
  const lanes = ids.length > 0 ? Math.max(...row.values()) + 1 : 0
  const fits = (count: number) => count * CARD_MIN_W + Math.max(0, count - 1) * GAP_MIN + 2 * PAD <= opts.width
  const orientation: Orientation =
    opts.orientation && opts.orientation !== 'auto' ? opts.orientation : opts.width >= PHONE_W && fits(cols) ? 'horizontal' : 'vertical'
  // The only final step gets a result card in an extra last column when that column still fits.
  const finals = graph.nodes.filter((node) => node.is_final_output)
  const final = orientation === 'horizontal' && finals.length === 1 && fits(cols + 1) ? finals[0].node_id : null
  const columns = cols + (final ? 1 : 0)
  const laidEdges: PipelineGraphEdge[] = [...graphEdges]
  if (final) {
    col.set(RESULT_ID, cols)
    row.set(RESULT_ID, row.get(final)!)
    laidEdges.push({ source: final, target: RESULT_ID, kind: 'flow', observed_count: 0, trace_coverage: 0, conditional: false, source_evidence: 'inferred' })
  }

  let place: (c: number, r: number) => { x: number; y: number }
  let w: number
  let width: number
  let height: number
  let overflowX = false
  if (orientation === 'horizontal') {
    const s = stretch(columns, opts.width - 2 * PAD)
    w = s.w
    place = (c, r) => ({ x: PAD + c * (s.w + s.gap), y: PAD + r * (CARD_H + ROW_GAP) })
    width = 2 * PAD + columns * s.w + Math.max(0, columns - 1) * s.gap
    height = 2 * PAD + Math.max(0, lanes - 1) * (CARD_H + ROW_GAP) + (lanes > 0 ? CARD_H : 0)
  } else {
    // Lanes become columns. The side padding gives way before the diagram scrolls sideways.
    const needed = lanes * CARD_MIN_W + Math.max(0, lanes - 1) * GAP_MIN
    overflowX = needed > opts.width
    const pad = overflowX ? PAD : Math.min(PAD, Math.floor((opts.width - needed) / 2))
    const s = overflowX ? { w: CARD_MIN_W, gap: GAP_MIN } : stretch(lanes, opts.width - 2 * pad)
    w = s.w
    place = (c, r) => ({ x: pad + r * (s.w + s.gap), y: PAD + c * (CARD_H + LEVEL_GAP) })
    width = 2 * pad + lanes * s.w + Math.max(0, lanes - 1) * s.gap
    height = 2 * PAD + Math.max(0, cols - 1) * (CARD_H + LEVEL_GAP) + (cols > 0 ? CARD_H : 0)
  }

  const nodes: FlowNode[] = graph.nodes.map((node) => {
    const c = col.get(node.node_id)!
    const r = row.get(node.node_id)!
    return { ...node, ...place(c, r), w, h: CARD_H, col: c, row: r }
  })
  const at = new Map<string, { x: number; y: number; w: number; h: number }>(nodes.map((node) => [node.node_id, node]))
  if (final) at.set(RESULT_ID, { ...place(cols, row.get(final)!), w, h: CARD_H })

  // Several edges entering (or leaving) one card share its side in lane order.
  const rank = (list: PipelineGraphEdge[], end: 'source' | 'target') =>
    [...list].sort((a, b) => row.get(a[end])! - row.get(b[end])! || col.get(a[end])! - col.get(b[end])! || byId(a[end], b[end]))
  const ends = [...at.keys()]
  const incoming = new Map(ends.map((id) => [id, rank(laidEdges.filter((e) => e.target === id), 'source')]))
  const outgoing = new Map(ends.map((id) => [id, rank(laidEdges.filter((e) => e.source === id), 'target')]))

  const edges: FlowEdge[] = laidEdges.map((edge) => {
    const s = at.get(edge.source)!
    const t = at.get(edge.target)!
    const outs = outgoing.get(edge.source)!
    const ins = incoming.get(edge.target)!
    const so = spread(outs.length, outs.indexOf(edge))
    const to = spread(ins.length, ins.indexOf(edge))
    let path: string
    let mid: { x: number; y: number }
    if (orientation === 'horizontal') {
      const x1 = s.x + s.w
      const y1 = s.y + s.h * so
      const x2 = t.x
      const y2 = t.y + t.h * to
      const mx = (x1 + x2) / 2
      path = `M ${x1} ${y1} C ${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`
      mid = { x: mx, y: (y1 + y2) / 2 }
    } else {
      const x1 = s.x + s.w * so
      const y1 = s.y + s.h
      const x2 = t.x + t.w * to
      const y2 = t.y
      const my = (y1 + y2) / 2
      path = `M ${x1} ${y1} C ${x1} ${my} ${x2} ${my} ${x2} ${y2}`
      mid = { x: (x1 + x2) / 2, y: my }
    }
    return { source: edge.source, target: edge.target, kind: edge.kind, conditional: edge.conditional, path, mid }
  })

  const resultEdge = final ? edges.pop()! : null
  const result = final ? { ...at.get(RESULT_ID)!, edge: resultEdge! } : null
  return { orientation, nodes, edges, result, width, height, overflowX }
}
