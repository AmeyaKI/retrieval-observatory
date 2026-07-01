import { useEffect, useMemo, useState } from 'react'
import { fetchOperatorDag, OperatorDag, OperatorDagNode } from '../api'
import NoData from './NoData'
import SectionHeading from './SectionHeading'

interface Props {
  dbId: string
  runId: string
  onSelectOp?: (opId: string) => void
}

const OP_COLORS: Record<string, string> = {
  SOURCE: 'bg-blue-100 border-blue-300 text-blue-800',
  FUSE: 'bg-purple-100 border-purple-300 text-purple-800',
  RERANK: 'bg-orange-100 border-orange-300 text-orange-800',
  BOOST: 'bg-green-100 border-green-300 text-green-800',
  EXPAND: 'bg-teal-100 border-teal-300 text-teal-800',
  FILTER: 'bg-red-100 border-red-300 text-red-800',
  GATE: 'bg-yellow-100 border-yellow-300 text-yellow-800',
  TRANSFORM: 'bg-indigo-100 border-indigo-300 text-indigo-800',
}

function layerNodes(dag: OperatorDag): Map<string, number> {
  const layers = new Map<string, number>()
  const parentMap = new Map<string, string[]>()
  for (const e of dag.edges) {
    parentMap.set(e.target, [...(parentMap.get(e.target) || []), e.source])
  }
  const nodeIds = new Set(dag.nodes.map((n) => n.op_id))

  function computeLayer(opId: string): number {
    if (layers.has(opId)) return layers.get(opId)!
    const parents = parentMap.get(opId) || []
    const validParents = parents.filter((p) => nodeIds.has(p))
    const layer = validParents.length === 0 ? 0 : Math.max(...validParents.map(computeLayer)) + 1
    layers.set(opId, layer)
    return layer
  }

  for (const n of dag.nodes) computeLayer(n.op_id)
  return layers
}

export default function OperatorDagView({ dbId, runId, onSelectOp }: Props) {
  const [dag, setDag] = useState<OperatorDag | null>(null)
  useEffect(() => {
    fetchOperatorDag(dbId, runId).then(setDag).catch(() => setDag(null))
  }, [dbId, runId])

  const layers = useMemo(() => (dag ? layerNodes(dag) : new Map<string, number>()), [dag])

  const layeredNodes = useMemo(() => {
    if (!dag) return []
    const byLayer = new Map<number, OperatorDagNode[]>()
    for (const n of dag.nodes) {
      const layer = layers.get(n.op_id) ?? 0
      byLayer.set(layer, [...(byLayer.get(layer) || []), n])
    }
    return Array.from(byLayer.entries()).sort((a, b) => a[0] - b[0])
  }, [dag, layers])

  if (!dag || dag.nodes.length === 0) {
    return <NoData label="No operator DAG available. V2 traces may not be present for this run." />
  }

  return (
    <div>
      <SectionHeading title="Operator DAG" />
      <div className="overflow-x-auto border border-gray-200 rounded bg-white p-4">
        <div className="flex gap-8 items-start min-w-max">
          {layeredNodes.map(([layerIdx, nodes]) => (
            <div key={layerIdx} className="flex flex-col gap-3 items-center">
              <div className="text-[10px] text-gray-400 font-medium">Layer {layerIdx}</div>
              {nodes.map((node) => {
                const colorClass = OP_COLORS[node.op_type] || 'bg-gray-100 border-gray-300'
                return (
                  <button
                    key={node.op_id}
                    className={`rounded-lg border-2 px-3 py-2 text-xs cursor-pointer hover:shadow-md transition-shadow ${colorClass}`}
                    onClick={() => onSelectOp?.(node.op_id)}
                    title={`${node.op_type} | fire: ${(node.fire_rate * 100).toFixed(0)}% | latency: ${node.avg_latency_ms.toFixed(1)}ms`}
                  >
                    <div className="font-mono font-semibold">{node.op_name}</div>
                    <div className="text-[10px] opacity-70 mt-0.5">
                      {node.op_type} · {(node.fire_rate * 100).toFixed(0)}%
                      {node.avg_latency_ms > 0 && ` · ${node.avg_latency_ms.toFixed(0)}ms`}
                    </div>
                  </button>
                )
              })}
            </div>
          ))}
        </div>
        {dag.edges.length > 0 && (
          <div className="mt-3 text-[10px] text-gray-400 border-t border-gray-100 pt-2">
            Edges: {dag.edges.map((e) => `${e.source} → ${e.target}`).join(', ')}
          </div>
        )}
      </div>
    </div>
  )
}
