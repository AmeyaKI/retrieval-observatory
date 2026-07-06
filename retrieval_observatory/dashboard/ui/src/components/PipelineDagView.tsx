import { useEffect, useMemo, useState } from 'react'
import { fetchPipelineGraphs, GraphMetricValue, PipelineGraph, PipelineGraphNode } from '../api'
import { layoutPipelineGraph, LaidOutNode } from '../utils/dagLayout'
import { fmtQuality, fmtLatencyMs } from '../utils/format'
import { MetricTooltip } from './MetricTooltip'

interface Props {
  dbId: string
  runId: string
}

const OP_ACCENT: Record<string, { fill: string; stroke: string; text: string }> = {
  SOURCE: { fill: 'rgba(37,99,235,0.10)', stroke: 'rgba(37,99,235,0.55)', text: 'rgb(59,130,246)' },
  FUSE: { fill: 'rgba(139,92,246,0.12)', stroke: 'rgba(139,92,246,0.60)', text: 'rgb(167,139,250)' },
  RERANK: { fill: 'rgba(217,119,6,0.12)', stroke: 'rgba(217,119,6,0.55)', text: 'rgb(245,158,11)' },
  BOOST: { fill: 'rgba(5,150,105,0.12)', stroke: 'rgba(5,150,105,0.55)', text: 'rgb(16,185,129)' },
  EXPAND: { fill: 'rgba(13,148,136,0.12)', stroke: 'rgba(13,148,136,0.55)', text: 'rgb(45,212,191)' },
  FILTER: { fill: 'rgba(220,38,38,0.12)', stroke: 'rgba(220,38,38,0.55)', text: 'rgb(248,113,113)' },
  GATE: { fill: 'rgba(202,138,4,0.12)', stroke: 'rgba(202,138,4,0.55)', text: 'rgb(234,179,8)' },
  TRANSFORM: { fill: 'rgba(79,70,229,0.12)', stroke: 'rgba(79,70,229,0.55)', text: 'rgb(129,140,248)' },
}
const OP_LABEL: Record<string, string> = {
  SOURCE: 'Retrieval', FUSE: 'Fusion', RERANK: 'Reranking', BOOST: 'Boosting',
  EXPAND: 'Expansion', FILTER: 'Filtering', GATE: 'Gating', TRANSFORM: 'Transform',
}

function ci(v: GraphMetricValue | null | undefined): string {
  if (!v || v.ci_low == null || v.ci_high == null) return ''
  return `[${fmtQuality(v.ci_low)}, ${fmtQuality(v.ci_high)}]`
}

function MetricLine({ label, v, latency }: { label: string; v: GraphMetricValue | null | undefined; latency?: boolean }) {
  if (!v || v.mean == null) return null
  const bounds = ci(v)
  return (
    <div className="flex items-baseline justify-between gap-2 leading-tight">
      <span className="text-ink-faint">{label}</span>
      <span className="text-right">
        <span className="font-mono tabular-nums text-ink">
          {latency ? `${fmtLatencyMs(v.mean)} ms` : fmtQuality(v.mean)}
        </span>
        {bounds && <span className="block font-mono tabular-nums text-[9px] text-ink-faint">{bounds}</span>}
      </span>
    </div>
  )
}

function NodeCard({
  node,
  selected,
  onSelect,
}: {
  node: LaidOutNode
  selected: boolean
  onSelect: (id: string) => void
}) {
  const accent = OP_ACCENT[node.op_type] ?? OP_ACCENT.TRANSFORM
  const recallLabel = node.metrics.recall?.k ? `Recall@${node.metrics.recall.k}` : 'Recall'
  return (
    <foreignObject x={node.x} y={node.y} width={node.w} height={node.h}>
      <button
        type="button"
        onClick={() => onSelect(node.node_id)}
        className="h-full w-full rounded-xl px-3 py-2 flex flex-col gap-1 overflow-hidden text-left transition-shadow"
        style={{
          background: accent.fill,
          border: `${selected ? 2.5 : 1.5}px solid ${selected ? accent.text : accent.stroke}`,
          boxShadow: selected ? `0 0 0 2px ${accent.fill}` : undefined,
        }}
        title={`${node.op_type}${node.is_merge ? ' · merge point' : ''}`}
      >
        <div className="flex items-center justify-between gap-1">
          <span className="text-[9px] font-bold uppercase tracking-wide" style={{ color: accent.text }}>
            {OP_LABEL[node.op_type] ?? node.op_type}
          </span>
          {node.is_merge && (
            <span className="text-[8px] font-semibold rounded px-1 py-px" style={{ background: accent.stroke, color: '#fff' }}>
              MERGE
            </span>
          )}
        </div>
        <div className="text-xs font-semibold text-ink truncate">{node.label}</div>
        <div className="text-[10px] space-y-0.5 mt-auto">
          <MetricLine label="NDCG@10" v={node.metrics['ndcg@10']} />
          <MetricLine label={recallLabel} v={node.metrics.recall} />
          <MetricLine label="P50" v={node.metrics.latency_p50} latency />
        </div>
      </button>
    </foreignObject>
  )
}

function edgeMidpoint(path: string): { x: number; y: number } | null {
  const nums = path.match(/-?\d+\.?\d*/g)?.map(Number)
  if (!nums || nums.length < 4) return null
  const x1 = nums[0]
  const y1 = nums[1]
  const x2 = nums[nums.length - 2]
  const y2 = nums[nums.length - 1]
  return { x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 8 }
}

function GraphSvg({
  graph,
  selectedId,
  onSelect,
}: {
  graph: PipelineGraph
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const layout = useMemo(() => layoutPipelineGraph(graph), [graph])
  const nodeById = useMemo(() => new Map(graph.nodes.map((n) => [n.node_id, n])), [graph.nodes])

  return (
    <div className="overflow-x-auto">
      <svg width={layout.width} height={layout.height} className="min-w-max" role="img" aria-label={`Pipeline graph for ${graph.pipeline_id}`}>
        <defs>
          <marker id={`dag-arrow-${graph.pipeline_id}`} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse">
            <path d="M0,0 L8,4 L0,8 Z" fill="rgb(var(--ink-faint))" />
          </marker>
        </defs>
        {layout.edges.map((e, i) => {
          const target = nodeById.get(e.target)
          const mid = edgeMidpoint(e.path)
          const showCount = e.kind === 'flow' && target && target.candidate_count > 0 && mid
          return (
            <g key={i}>
              <path
                d={e.path}
                fill="none"
                stroke="rgb(var(--ink-faint))"
                strokeWidth={e.kind === 'fan_in' ? 2 : 1.5}
                strokeDasharray={e.kind === 'fan_in' ? '5 3' : undefined}
                markerEnd={`url(#dag-arrow-${graph.pipeline_id})`}
                opacity={0.7}
              />
              {showCount && (
                <text x={mid!.x} y={mid!.y} textAnchor="middle" fontSize={9} fill="rgb(var(--ink-faint))">
                  n≈{Math.round(target!.candidate_count)}
                </text>
              )}
            </g>
          )
        })}
        {layout.nodes.map((n) => (
          <NodeCard key={n.node_id} node={n} selected={selectedId === n.node_id} onSelect={onSelect} />
        ))}
      </svg>
    </div>
  )
}

function NodeInspector({ node }: { node: PipelineGraphNode }) {
  const accent = OP_ACCENT[node.op_type] ?? OP_ACCENT.TRANSFORM
  const recallLabel = node.metrics.recall?.k ? `Recall@${node.metrics.recall.k}` : 'Recall'
  return (
    <div className="app-inset p-3 text-xs space-y-2">
      <div className="flex items-center gap-2">
        <span className="font-semibold text-ink">{node.label}</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: accent.fill, color: accent.text }}>
          {OP_LABEL[node.op_type] ?? node.op_type}
        </span>
        {node.is_merge && <span className="text-[10px] text-ink-faint">merge · depth {node.depth}</span>}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 font-mono tabular-nums">
        <div><span className="text-ink-faint block">NDCG@10</span>{node.metrics['ndcg@10']?.mean != null ? fmtQuality(node.metrics['ndcg@10']!.mean!) : '—'}{ci(node.metrics['ndcg@10']) && ` ${ci(node.metrics['ndcg@10'])}`}</div>
        <div><span className="text-ink-faint block">{recallLabel}</span>{node.metrics.recall?.mean != null ? fmtQuality(node.metrics.recall.mean) : '—'}{ci(node.metrics.recall) && ` ${ci(node.metrics.recall)}`}</div>
        <div><span className="text-ink-faint block">P50</span>{node.metrics.latency_p50?.mean != null ? `${fmtLatencyMs(node.metrics.latency_p50.mean)} ms` : '—'}</div>
        <div><span className="text-ink-faint block">Candidates</span>{Math.round(node.candidate_count)}</div>
      </div>
    </div>
  )
}

export default function PipelineDagView({ dbId, runId }: Props) {
  const [graphs, setGraphs] = useState<PipelineGraph[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedByPipeline, setSelectedByPipeline] = useState<Record<string, string>>({})

  useEffect(() => {
    setGraphs(null)
    setError(null)
    setSelectedByPipeline({})
    fetchPipelineGraphs(dbId, runId)
      .then(setGraphs)
      .catch((e) => setError(e.message))
  }, [dbId, runId])

  if (error) return <p className="text-sm text-ink-faint">Pipeline graph unavailable: {error}</p>
  if (!graphs) return <p className="text-sm text-ink-faint">Loading pipeline graph…</p>
  if (graphs.length === 0) {
    return <p className="text-sm text-ink-faint">No topology recorded for this run.</p>
  }

  const opTypes = [...new Set(graphs.flatMap((g) => g.nodes.map((n) => n.op_type)))]

  return (
    <div className="space-y-5">
      <p className="text-xs text-ink-muted">
        Directed graph from measured traces: parallel branches <strong>merge</strong> at fusion nodes (dashed edges).
        Flow edges show approximate candidate count (n≈). Click a node for per-operator metrics and CIs.
        <MetricTooltip text="Same PipelineGraph contract as MCP get_pipeline_diagram and the offline HTML diagram export." />
      </p>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-ink-muted">
        {opTypes.map((t) => {
          const a = OP_ACCENT[t] ?? OP_ACCENT.TRANSFORM
          return (
            <span key={t} className="inline-flex items-center gap-1">
              <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: a.fill, border: `1.5px solid ${a.stroke}` }} />
              {OP_LABEL[t] ?? t}
            </span>
          )
        })}
      </div>
      {graphs.map((g) => {
        const selectedId = selectedByPipeline[g.pipeline_id] ?? g.nodes[g.nodes.length - 1]?.node_id ?? null
        const selectedNode = g.nodes.find((n) => n.node_id === selectedId) ?? null
        return (
          <div key={g.pipeline_id} className="app-card p-4 space-y-3">
            <div className="eyebrow">{g.pipeline_id.replace(/_/g, ' ')}</div>
            <GraphSvg
              graph={g}
              selectedId={selectedId}
              onSelect={(id) => setSelectedByPipeline((prev) => ({ ...prev, [g.pipeline_id]: id }))}
            />
            {selectedNode && <NodeInspector node={selectedNode} />}
          </div>
        )
      })}
    </div>
  )
}
