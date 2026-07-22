import { CandidateLineageEdge, CandidateLineageNode } from '../api'

type StageNode = { key: string; opId: string; opType: string; branchId: string | null; column: number; row: number }

function stageLayout(nodes: CandidateLineageNode[]): { stages: StageNode[]; links: Array<[string, string]> } {
  const stages = new Map<string, StageNode>()
  const links = new Set<string>()
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
          links.add(`${previous.op_id}:${previous.branch_id ?? ''}|${key}`)
        }
      })
    }
  }
  return { stages: [...stages.values()], links: [...links].map(link => link.split('|') as [string, string]) }
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
  const { stages, links } = stageLayout(nodes)
  const stageByKey = new Map(stages.map(stage => [stage.key, stage]))
  const selected = nodes.find(node => node.node_id === selectedNodeId)
  const selectedStageKeys = new Set(selected?.routes.flatMap(route => route.stages.map(stage => `${stage.op_id}:${stage.branch_id ?? ''}`)) ?? [])
  const width = Math.max(520, (Math.max(...stages.map(stage => stage.column), 0) + 1) * 190 + 40)
  const height = Math.max(170, (Math.max(...stages.map(stage => stage.row), 0) + 1) * 100 + 50)

  return (
    <section aria-labelledby="candidate-lineage-heading" className="space-y-3">
      <div>
        <h3 id="candidate-lineage-heading" className="text-sm font-semibold text-ink">Static candidate lineage</h3>
        <p className="text-xs text-ink-muted">Recorded routes only. Branch labels and node shapes supplement color; missing capture is not inferred.</p>
      </div>
      {stages.length > 0 ? (
        <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700" tabIndex={0}>
          <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Recorded branch-aware retrieval stage graph" className="block min-w-max">
            <defs><marker id="lineage-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="rgb(100 116 139)" /></marker></defs>
            {links.map(([fromKey, toKey]) => {
              const from = stageByKey.get(fromKey); const to = stageByKey.get(toKey)
              if (!from || !to) return null
              const active = selectedStageKeys.has(fromKey) && selectedStageKeys.has(toKey)
              return <path key={`${fromKey}-${toKey}`} d={`M ${from.column * 190 + 160} ${from.row * 100 + 55} C ${from.column * 190 + 180} ${from.row * 100 + 55}, ${to.column * 190 + 20} ${to.row * 100 + 55}, ${to.column * 190 + 30} ${to.row * 100 + 55}`} fill="none" stroke={active ? 'rgb(79 70 229)' : 'rgb(148 163 184)'} strokeWidth={active ? 4 : 2} markerEnd="url(#lineage-arrow)" />
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
        {nodes.length === 0 ? <p className="text-xs text-ink-muted">No candidate routes were captured.</p> : nodes.map(node => (
          <button key={node.node_id} type="button" aria-pressed={node.node_id === selectedNodeId} onClick={() => onSelect(node.node_id)} className={`block w-full rounded border p-2 text-left text-xs ${node.node_id === selectedNodeId ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30' : 'border-slate-200 dark:border-slate-700'}`}>
            <span className="font-mono font-semibold">{node.candidate_id}</span>
            <span className="ml-2 text-ink-muted">{node.trace_id} · {node.pipeline_id}</span>
            <span className="block text-ink-faint">{node.routes.length ? node.routes.map(route => `${route.operator_ids.join(' → ') || 'operators unavailable'}${route.branch_ids.length ? ` (${route.branch_ids.join(', ')})` : ''}`).join(' | ') : 'route unavailable'} · {node.outcome.kind.replace(/_/g, ' ')}</span>
          </button>
        ))}
        {edges.length > 0 ? <p className="text-[10px] text-ink-faint">{edges.length} recorded candidate-parent transition{edges.length === 1 ? '' : 's'}.</p> : null}
      </div>
    </section>
  )
}
