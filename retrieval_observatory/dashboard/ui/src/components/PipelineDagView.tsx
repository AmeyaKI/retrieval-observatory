import { useEffect, useMemo, useState } from 'react'
import { fetchPipelineGraphs, fetchRunTraces, GraphMetricValue, PipelineGraph, PipelineGraphNode, RetrievalTrace } from '../api'
import { layoutPipelineGraph, LaidOutNode } from '../utils/dagLayout'
import { fmtQuality, fmtLatencyMs } from '../utils/format'
import { OP_ACCENT, OP_LABEL } from '../utils/opTypeColors'
import { MetricTooltip } from './MetricTooltip'

interface Props {
  dbId: string
  runId: string
}

function ci(v: GraphMetricValue | null | undefined): string {
  if (!v || v.ci_low == null || v.ci_high == null) return ''
  return `[${fmtQuality(v.ci_low)}, ${fmtQuality(v.ci_high)}]`
}

function MetricLine({ label, v, latency }: { label: string; v: GraphMetricValue | null | undefined; latency?: boolean }) {
  if (!v || v.mean == null) return null
  return (
    <div className="flex items-baseline justify-between gap-2 leading-tight whitespace-nowrap">
      <span className="text-ink-faint shrink-0">{label}</span>
      <span className="font-mono tabular-nums text-ink truncate" title={ci(v) || undefined}>
        {latency ? `${fmtLatencyMs(v.mean)} ms` : fmtQuality(v.mean)}
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
  const status = Object.entries(node.status_counts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'UNOBSERVED'
  const tip = [
    node.label,
    `${node.op_type}${node.is_merge ? ' · merge' : ''}`,
    status,
    node.metrics['ndcg@10']?.mean != null ? `NDCG@10 ${fmtQuality(node.metrics['ndcg@10'].mean)}${ci(node.metrics['ndcg@10']) ? ` ${ci(node.metrics['ndcg@10'])}` : ''}` : null,
    node.metrics.recall?.mean != null ? `${recallLabel} ${fmtQuality(node.metrics.recall.mean)}${ci(node.metrics.recall) ? ` ${ci(node.metrics.recall)}` : ''}` : null,
    node.metrics.latency_p50?.mean != null ? `P50 ${fmtLatencyMs(node.metrics.latency_p50.mean)} ms` : null,
  ]
    .filter(Boolean)
    .join('\n')
  return (
    <foreignObject x={node.x} y={node.y} width={node.w} height={node.h} style={{ overflow: 'visible' }}>
      <button
        type="button"
        onClick={() => onSelect(node.node_id)}
        className="box-border h-full w-full rounded-xl px-2.5 py-2 flex flex-col gap-0.5 text-left transition-shadow"
        style={{
          background: accent.fill,
          border: `${selected ? 2.5 : 1.5}px solid ${selected ? accent.text : accent.stroke}`,
          boxShadow: selected ? `0 0 0 2px ${accent.fill}` : undefined,
          width: node.w,
          height: node.h,
        }}
        title={tip}
      >
        <div className="flex items-center justify-between gap-1 min-w-0">
          <span className="text-[9px] font-bold uppercase tracking-wide truncate" style={{ color: accent.text }}>
            {OP_LABEL[node.op_type] ?? node.op_type}
          </span>
          {node.is_merge && (
            <span className="shrink-0 text-[8px] font-semibold rounded px-1 py-px" style={{ background: accent.stroke, color: '#fff' }}>
              MERGE
            </span>
          )}
        </div>
        <div className="text-xs font-semibold text-ink leading-snug break-words line-clamp-2">{node.label}</div>
        <div className="text-[9px] text-ink-muted truncate">
          {status} · fire {(node.fire_rate * 100).toFixed(0)}%
          {node.cache_hits ? ` · ${node.cache_hits} cache` : ''}
        </div>
        <div className="text-[10px] space-y-0.5 mt-auto min-w-0">
          <MetricLine label="NDCG@10" v={node.metrics['ndcg@10']} />
          <MetricLine label={recallLabel} v={node.metrics.recall} />
          <MetricLine label="P50" v={node.metrics.latency_p50} latency />
        </div>
      </button>
    </foreignObject>
  )
}

function GraphTable({ graph }: { graph: PipelineGraph }) {
  const parents = new Map<string, string[]>()
  for (const edge of graph.edges) parents.set(edge.target, [...(parents.get(edge.target) ?? []), edge.source])
  return (
    <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
      <table className="w-full text-left text-xs">
        <caption className="sr-only">Accessible operator table for pipeline {graph.pipeline_id}</caption>
        <thead className="bg-surface-muted">
          <tr><th className="p-2">Operator</th><th className="p-2">Parents</th><th className="p-2">Observed status</th><th className="p-2">Coverage / fire</th><th className="p-2">Candidates</th><th className="p-2">Latency</th><th className="p-2">Final</th><th className="p-2">Evidence</th></tr>
        </thead>
        <tbody>{graph.nodes.map((node) => (
          <tr key={node.node_id} className="border-t border-slate-200 dark:border-slate-700">
            <th scope="row" className="p-2"><span className="font-medium">{node.label}</span><span className="block font-mono text-[10px] text-ink-faint">{node.op_type} · {node.node_id}</span></th>
            <td className="p-2 font-mono">{(parents.get(node.node_id) ?? []).join(', ') || 'source'}</td>
            <td className="p-2">{Object.entries(node.status_counts).map(([status, count]) => `${status} ${count}`).join(', ') || 'unobserved'}</td>
            <td className="p-2">{(node.trace_coverage * 100).toFixed(0)}% / {(node.fire_rate * 100).toFixed(0)}%</td>
            <td className="p-2">in {node.input_candidate_count} · out {Math.round(node.candidate_count)}</td>
            <td className="p-2">p50 {node.latency.p50_ms == null ? 'unavailable' : `${fmtLatencyMs(node.latency.p50_ms)} ms`}</td>
            <td className="p-2">{node.is_final_output ? `yes (${node.final_output_count})` : 'no'}</td>
            <td className="p-2">{node.source}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
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
    <div className="overflow-x-auto overflow-y-visible pb-2">
      <svg
        width={layout.width}
        height={layout.height}
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        className="min-w-max block"
        role="img"
        aria-label={`Pipeline graph for ${graph.pipeline_id}`}
      >
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
  const [traceOptions, setTraceOptions] = useState<RetrievalTrace[]>([])
  const [selectedTraceId, setSelectedTraceId] = useState('')

  useEffect(() => {
    fetchRunTraces(dbId, runId, 50).then(setTraceOptions).catch(() => setTraceOptions([]))
  }, [dbId, runId])

  useEffect(() => {
    setGraphs(null)
    setError(null)
    setSelectedByPipeline({})
    fetchPipelineGraphs(dbId, runId, selectedTraceId || undefined)
      .then(setGraphs)
      .catch((e) => setError(e.message))
  }, [dbId, runId, selectedTraceId])

  if (error) return <p className="text-sm text-ink-faint">Pipeline graph unavailable: {error}</p>
  if (!graphs) return <p className="text-sm text-ink-faint">Loading pipeline graph…</p>
  if (graphs.length === 0) {
    return <p className="text-sm text-ink-faint">No topology recorded for this run.</p>
  }

  const opTypes = [...new Set(graphs.flatMap((g) => g.nodes.map((n) => n.op_type)))]

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3 rounded border border-slate-200 dark:border-slate-700 bg-surface-muted p-3">
        <label className="text-xs text-ink"><span className="mb-1 block font-medium">Projection</span>
          <select value={selectedTraceId} onChange={(event) => setSelectedTraceId(event.target.value)} className="rounded border border-slate-300 bg-surface px-2 py-1.5 text-xs">
            <option value="">Run union (aggregate)</option>
            {traceOptions.map((trace) => <option key={trace.trace_id} value={trace.trace_id}>Exact trace · {trace.query_id} · {trace.pipeline_id} · {trace.status}</option>)}
          </select>
        </label>
        <p className="text-xs text-ink-muted">{selectedTraceId ? 'Exact nodes, edges, statuses, gates, final output, and candidates from one trace.' : 'Union of every observed path with coverage and fire rates.'}</p>
      </div>
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
            <div className="flex flex-wrap items-center gap-2"><div className="eyebrow">{g.pipeline_id.replace(/_/g, ' ')}</div><span className="rounded border px-1.5 py-0.5 text-[10px]">{g.projection_mode === 'trace' ? 'Exact trace' : 'Run union'}</span><span className="text-[10px] text-ink-muted">{g.complete_trace_count}/{g.trace_count} complete</span></div>
            {g.warnings.length > 0 && <ul className="list-disc pl-5 text-xs text-amber-800 dark:text-amber-300">{g.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
            <GraphSvg
              graph={g}
              selectedId={selectedId}
              onSelect={(id) => setSelectedByPipeline((prev) => ({ ...prev, [g.pipeline_id]: id }))}
            />
            {selectedNode && <NodeInspector node={selectedNode} />}
            <details>
              <summary className="cursor-pointer text-xs font-medium text-indigo-700 dark:text-indigo-300">Operator table (accessible equivalent)</summary>
              <div className="mt-2"><GraphTable graph={g} /></div>
            </details>
          </div>
        )
      })}
    </div>
  )
}
