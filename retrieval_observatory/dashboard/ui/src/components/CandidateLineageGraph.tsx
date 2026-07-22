import { useMemo, useState } from 'react'
import { CandidateLineageEdge, CandidateLineageNode } from '../api'

type StageNode = { key: string; opId: string; opType: string; branchId: string | null; column: number; row: number }

function stageLayout(nodes: CandidateLineageNode[]): { stages: StageNode[]; links: Array<{ from: string; to: string; count: number }> } {
  const stages = new Map<string, StageNode>()
  const links = new Map<string, number>()
  const rows = new Map<string, number>()
  for (const candidate of nodes) {
    for (const route of candidate.routes) {
      route.stages.forEach((stage, index) => {
        const key = `${stage.op_id}:${stage.branch_id ?? ''}`
        const branch = stage.branch_id ?? 'main'
        if (!rows.has(branch)) rows.set(branch, rows.size)
        if (!stages.has(key)) stages.set(key, { key, opId: stage.op_id, opType: stage.op_type, branchId: stage.branch_id, column: index, row: rows.get(branch)! })
        if (index > 0) {
          const previous = route.stages[index - 1]
          const link = `${previous.op_id}:${previous.branch_id ?? ''}|${key}`
          links.set(link, (links.get(link) ?? 0) + 1)
        }
      })
    }
  }
  return { stages: [...stages.values()], links: [...links].map(([link, count]) => { const [from, to] = link.split('|'); return { from, to, count } }) }
}

export default function CandidateLineageGraph({
  nodes,
  edges,
  selectedNodeId,
  onSelect,
}: {
  nodes: CandidateLineageNode[]
  edges: CandidateLineageEdge[]
  selectedNodeId: string | null
  onSelect: (nodeId: string) => void
}) {
  const [branchFilter, setBranchFilter] = useState('')
  const [stageFilter, setStageFilter] = useState('')
  const [outcomeFilter, setOutcomeFilter] = useState('')
  const [evidenceFilter, setEvidenceFilter] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const branches = useMemo(() => [...new Set(nodes.flatMap(node => node.routes.flatMap(route => route.branch_ids)))].sort(), [nodes])
  const stageIds = useMemo(() => [...new Set(nodes.flatMap(node => node.routes.flatMap(route => route.operator_ids)))].sort(), [nodes])
  const outcomes = useMemo(() => [...new Set(nodes.map(node => node.outcome.kind))].sort(), [nodes])
  const evidenceStates = useMemo(() => [...new Set(nodes.map(node => node.lineage_evidence))].sort(), [nodes])
  const visibleNodes = useMemo(() => nodes.filter(node => {
    const source = sourceFilter.trim().toLowerCase()
    return (!branchFilter || node.routes.some(route => route.branch_ids.includes(branchFilter)))
      && (!stageFilter || node.routes.some(route => route.operator_ids.includes(stageFilter)))
      && (!outcomeFilter || node.outcome.kind === outcomeFilter)
      && (!evidenceFilter || node.lineage_evidence === evidenceFilter)
      && (!source || [node.candidate_id, node.logical_chunk_id, node.source.document_id].some(value => value?.toLowerCase().includes(source)))
  }), [nodes, branchFilter, stageFilter, outcomeFilter, evidenceFilter, sourceFilter])
  const visibleNodeIds = new Set(visibleNodes.map(node => node.node_id))
  const visibleEdges = edges.filter(edge => visibleNodeIds.has(edge.source_node_id) && visibleNodeIds.has(edge.target_node_id))
  const { stages, links } = stageLayout(visibleNodes)
  const stageByKey = new Map(stages.map(stage => [stage.key, stage]))
  const selected = visibleNodes.find(node => node.node_id === selectedNodeId)
  const selectedStageKeys = new Set(selected?.routes.flatMap(route => route.stages.map(stage => `${stage.op_id}:${stage.branch_id ?? ''}`)) ?? [])
  const width = Math.max(520, (Math.max(...stages.map(stage => stage.column), 0) + 1) * 190 + 40)
  const height = Math.max(170, (Math.max(...stages.map(stage => stage.row), 0) + 1) * 100 + 50)

  return (
    <section aria-labelledby="candidate-lineage-heading" className="space-y-3">
      <div>
        <h3 id="candidate-lineage-heading" className="text-sm font-semibold text-ink">Static candidate lineage</h3>
        <p className="text-xs text-ink-muted">Recorded routes only. Branch labels and node shapes supplement color; missing capture is not inferred.</p>
      </div>
      <div className="grid gap-2 rounded border border-slate-200 dark:border-slate-700 p-2 sm:grid-cols-2 lg:grid-cols-5">
        <label className="text-[10px] text-ink-faint">Filter by branch<select aria-label="Filter by branch" value={branchFilter} onChange={event => setBranchFilter(event.target.value)} className="mt-1 block w-full rounded border bg-surface p-1 text-xs text-ink"><option value="">All branches</option>{branches.map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="text-[10px] text-ink-faint">Filter by stage<select aria-label="Filter by stage" value={stageFilter} onChange={event => setStageFilter(event.target.value)} className="mt-1 block w-full rounded border bg-surface p-1 text-xs text-ink"><option value="">All stages</option>{stageIds.map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="text-[10px] text-ink-faint">Filter by outcome<select aria-label="Filter by outcome" value={outcomeFilter} onChange={event => setOutcomeFilter(event.target.value)} className="mt-1 block w-full rounded border bg-surface p-1 text-xs text-ink"><option value="">All outcomes</option>{outcomes.map(value => <option key={value}>{value.replace(/_/g, ' ')}</option>)}</select></label>
        <label className="text-[10px] text-ink-faint">Filter by evidence<select aria-label="Filter by evidence" value={evidenceFilter} onChange={event => setEvidenceFilter(event.target.value)} className="mt-1 block w-full rounded border bg-surface p-1 text-xs text-ink"><option value="">All evidence</option>{evidenceStates.map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="text-[10px] text-ink-faint">Filter by source<input aria-label="Filter by source" value={sourceFilter} onChange={event => setSourceFilter(event.target.value)} placeholder="candidate, chunk, document" className="mt-1 block w-full rounded border bg-surface p-1 text-xs text-ink" /></label>
        <p className="sm:col-span-2 lg:col-span-5 text-[10px] text-ink-faint">Showing {visibleNodes.length} of {nodes.length} candidates.</p>
      </div>
      {stages.length > 0 ? (
        <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700" tabIndex={0}>
          <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Recorded branch-aware retrieval stage graph" className="block min-w-max">
            <defs><marker id="lineage-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="rgb(100 116 139)" /></marker></defs>
            {links.map(({ from: fromKey, to: toKey, count }) => {
              const from = stageByKey.get(fromKey); const to = stageByKey.get(toKey)
              if (!from || !to) return null
              const active = selectedStageKeys.has(fromKey) && selectedStageKeys.has(toKey)
              return <path key={`${fromKey}-${toKey}`} d={`M ${from.column * 190 + 160} ${from.row * 100 + 55} C ${from.column * 190 + 180} ${from.row * 100 + 55}, ${to.column * 190 + 20} ${to.row * 100 + 55}, ${to.column * 190 + 30} ${to.row * 100 + 55}`} fill="none" stroke={active ? 'rgb(79 70 229)' : 'rgb(148 163 184)'} strokeWidth={active ? 4 : Math.min(7, 1.5 + Math.log2(count + 1))} markerEnd="url(#lineage-arrow)" />
            })}
            {stages.map(stage => {
              const active = selectedStageKeys.has(stage.key)
              const x = stage.column * 190 + 30; const y = stage.row * 100 + 25
              return <g key={stage.key}>
                <rect x={x} y={y} width="130" height="60" rx={stage.branchId ? 4 : 14} fill={active ? 'rgb(224 231 255)' : 'rgb(248 250 252)'} stroke={active ? 'rgb(79 70 229)' : 'rgb(100 116 139)'} strokeWidth={active ? 3 : 1.5} />
                <text x={x + 10} y={y + 24} className="fill-ink text-[11px] font-semibold">{stage.opId}</text>
                <text x={x + 10} y={y + 42} className="fill-slate-500 text-[9px]">{stage.opType} · {stage.branchId ?? 'main'}</text>
              </g>
            })}
          </svg>
        </div>
      ) : <p className="rounded border border-dashed p-3 text-xs text-ink-muted">Stage topology is unavailable in the captured lineage.</p>}

      <div aria-label="Recorded candidate routes" className="space-y-1">
        <h4 className="text-xs font-semibold text-ink">Recorded candidate routes</h4>
        {visibleNodes.length === 0 ? <p className="text-xs text-ink-muted">No candidate routes match the active filters.</p> : visibleNodes.map(node => (
          <button key={node.node_id} type="button" aria-pressed={node.node_id === selectedNodeId} onClick={() => onSelect(node.node_id)} className={`block w-full rounded border p-2 text-left text-xs ${node.node_id === selectedNodeId ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30' : 'border-slate-200 dark:border-slate-700'}`}>
            <span className="font-mono font-semibold">{node.candidate_id}</span>
            <span className="ml-2 text-ink-muted">{node.trace_id} · {node.pipeline_id}</span>
            <span className="block text-ink-faint">{node.routes.length ? node.routes.map(route => `${route.operator_ids.join(' → ') || 'operators unavailable'}${route.branch_ids.length ? ` (${route.branch_ids.join(', ')})` : ''}`).join(' | ') : 'route unavailable'} · {node.outcome.kind.replace(/_/g, ' ')}</span>
          </button>
        ))}
        {visibleEdges.length > 0 ? <p className="text-[10px] text-ink-faint">{visibleEdges.length} recorded candidate-parent transition{visibleEdges.length === 1 ? '' : 's'} in the filtered view.</p> : null}
      </div>
    </section>
  )
}
