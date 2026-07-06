import { PipelineGraph, PipelineGraphNode } from '../api'

// Pure, dependency-free layered DAG layout. x is driven by topological depth (columns);
// nodes sharing a depth are stacked vertically and centered. Output is a pure function of the
// input graph so it can be unit-tested (rendered geometry == computed geometry).

export const NODE_W = 184
export const NODE_H = 96
export const COL_GAP = 72
export const ROW_GAP = 28
export const PAD = 16

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
  const maxRows = Math.max(1, ...[...byDepth.values()].map((l) => l.length))
  const colHeight = maxRows * NODE_H + (maxRows - 1) * ROW_GAP

  const positioned = new Map<string, LaidOutNode>()
  depths.forEach((depth, colIdx) => {
    const list = byDepth.get(depth)!
    const stackH = list.length * NODE_H + (list.length - 1) * ROW_GAP
    const yOffset = PAD + (colHeight - stackH) / 2
    list.forEach((node, rowIdx) => {
      positioned.set(node.node_id, {
        ...node,
        x: PAD + colIdx * (NODE_W + COL_GAP),
        y: yOffset + rowIdx * (NODE_H + ROW_GAP),
        w: NODE_W,
        h: NODE_H,
      })
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
