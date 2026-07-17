import { PipelineGraph, PipelineGraphNode } from '../api'

// Pure, dependency-free layered DAG layout. x is driven by topological depth (columns);
// nodes sharing a depth are stacked vertically and centered. Output is a pure function of the
// input graph so it can be unit-tested (rendered geometry == computed geometry).

export const NODE_W = 200
/** Compact card height: type + label + status + up to 3 single-line metrics. */
export const NODE_H = 118
export const COL_GAP = 80
export const ROW_GAP = 36
export const PAD = 20

export interface LaidOutNode extends PipelineGraphNode {
  x: number
  y: number
  w: number
  h: number
}

export interface LaidOutEdge {
  source: string
  target: string
  kind: 'flow' | 'fan_in'
  path: string
}

export interface DagLayout {
  nodes: LaidOutNode[]
  edges: LaidOutEdge[]
  width: number
  height: number
}

/** Card height fits type/label/status plus one line per present metric (no CI on card). */
export function nodeCardHeight(node: PipelineGraphNode): number {
  let metrics = 0
  if (node.metrics['ndcg@10']?.mean != null) metrics += 1
  if (node.metrics.recall?.mean != null) metrics += 1
  if (node.metrics.latency_p50?.mean != null) metrics += 1
  // header block (~58) + metric rows; empty-metric nodes stay at NODE_H
  if (metrics === 0) return NODE_H
  return 58 + metrics * 22
}

export function layoutPipelineGraph(graph: PipelineGraph): DagLayout {
  const byDepth = new Map<number, PipelineGraphNode[]>()
  for (const node of graph.nodes) {
    const list = byDepth.get(node.depth) ?? []
    list.push(node)
    byDepth.set(node.depth, list)
  }
  for (const list of byDepth.values()) {
    list.sort((a, b) => a.node_id.localeCompare(b.node_id))
  }

  const depths = [...byDepth.keys()].sort((a, b) => a - b)
  const heightsByDepth = new Map<number, number[]>()
  for (const [depth, list] of byDepth) {
    heightsByDepth.set(
      depth,
      list.map((n) => nodeCardHeight(n)),
    )
  }

  const stackHeight = (hs: number[]) =>
    hs.reduce((a, b) => a + b, 0) + Math.max(0, hs.length - 1) * ROW_GAP

  const colHeights = depths.map((d) => stackHeight(heightsByDepth.get(d) ?? [NODE_H]))
  const colHeight = Math.max(1, ...colHeights, NODE_H)

  const positioned = new Map<string, LaidOutNode>()
  depths.forEach((depth, colIdx) => {
    const list = byDepth.get(depth)!
    const heights = heightsByDepth.get(depth)!
    const stackH = stackHeight(heights)
    let y = PAD + (colHeight - stackH) / 2
    list.forEach((node, rowIdx) => {
      const h = heights[rowIdx]
      positioned.set(node.node_id, {
        ...node,
        x: PAD + colIdx * (NODE_W + COL_GAP),
        y,
        w: NODE_W,
        h,
      })
      y += h + ROW_GAP
    })
  })

  const edges: LaidOutEdge[] = []
  for (const edge of graph.edges) {
    const s = positioned.get(edge.source)
    const t = positioned.get(edge.target)
    if (!s || !t) continue
    const x1 = s.x + s.w
    const y1 = s.y + s.h / 2
    const x2 = t.x
    const y2 = t.y + t.h / 2
    const mx = (x1 + x2) / 2
    edges.push({
      source: edge.source,
      target: edge.target,
      kind: edge.kind,
      path: `M ${x1} ${y1} C ${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`,
    })
  }

  const width = PAD * 2 + depths.length * NODE_W + Math.max(0, depths.length - 1) * COL_GAP
  const height = PAD * 2 + colHeight
  return { nodes: [...positioned.values()], edges, width, height }
}
