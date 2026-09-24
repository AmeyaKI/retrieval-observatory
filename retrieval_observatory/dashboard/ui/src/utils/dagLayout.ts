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

/** `cardHeight` defaults to the metric-card height; callers that render a different card pass their own. */
export function layoutPipelineGraph(graph: PipelineGraph, cardHeight: (node: PipelineGraphNode) => number = nodeCardHeight): DagLayout {
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
      list.map((n) => cardHeight(n)),
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

// ── Repeated invocations ────────────────────────────────────────────────────────────
// A trace names the second call of an operator `op#2`, the third `op#3` (tracing/model.py
// next_node_id). The investigation graph folds them onto the stable operator by default.

const REPEAT = /^(.+)#\d+$/

/** `rerank#2` → `rerank`; a node id without a repeat suffix is returned unchanged. */
export function collapsedNodeId(nodeId: string): string {
  return nodeId.match(REPEAT)?.[1] ?? nodeId
}

/** Number of repeat-invocation nodes (`op#2`, `op#3`, …) in the graph. */
export function repeatedInvocationCount(graph: PipelineGraph): number {
  return graph.nodes.filter((node) => REPEAT.test(node.node_id)).length
}

function sumCounts(a: Record<string, number>, b: Record<string, number>): Record<string, number> {
  const out = { ...a }
  for (const [key, value] of Object.entries(b)) out[key] = (out[key] ?? 0) + value
  return out
}

/** Merge every `op#N` node into `op`: counts are summed, `trace_coverage` takes the max, `depth`
 * the min, the label stays the base node's; edges are remapped, self-loops dropped and duplicates
 * merged. A graph without repeats is returned as is. */
export function collapseInvocations(graph: PipelineGraph): PipelineGraph {
  if (repeatedInvocationCount(graph) === 0) return graph
  const merged = new Map<string, PipelineGraphNode>()
  for (const node of graph.nodes) {
    const id = collapsedNodeId(node.node_id)
    const base = merged.get(id)
    if (!base) {
      merged.set(id, { ...node, node_id: id, status_counts: { ...node.status_counts } })
      continue
    }
    // Insertion order follows graph.nodes, so a base node that appears after its repeats still wins the label.
    const isBase = node.node_id === id
    merged.set(id, {
      ...base,
      label: isBase ? node.label : base.label,
      depth: Math.min(base.depth, node.depth),
      observed_count: base.observed_count + node.observed_count,
      candidate_count: base.candidate_count + node.candidate_count,
      input_candidate_count: base.input_candidate_count + node.input_candidate_count,
      final_output_count: base.final_output_count + node.final_output_count,
      status_counts: sumCounts(base.status_counts, node.status_counts),
      trace_coverage: Math.max(base.trace_coverage, node.trace_coverage),
      is_final_output: base.is_final_output || node.is_final_output,
    })
  }
  const edges = new Map<string, PipelineGraph['edges'][number]>()
  for (const edge of graph.edges) {
    const source = collapsedNodeId(edge.source)
    const target = collapsedNodeId(edge.target)
    if (source === target) continue
    const key = `${source}→${target}`
    const existing = edges.get(key)
    edges.set(
      key,
      existing
        ? { ...existing, observed_count: existing.observed_count + edge.observed_count, trace_coverage: Math.max(existing.trace_coverage, edge.trace_coverage) }
        : { ...edge, source, target },
    )
  }
  return {
    ...graph,
    nodes: [...merged.values()],
    edges: [...edges.values()],
    final_output_ids: [...new Set(graph.final_output_ids.map(collapsedNodeId))],
  }
}
