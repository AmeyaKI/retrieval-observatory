import { useMemo } from 'react'
import SectionHeading from './SectionHeading'
import NoData from './NoData'

interface Node {
  id: string
  label: string
  type?: string
}

interface Link {
  source: string
  target: string
  value: number
  dropped?: boolean
  expanded?: boolean
}

interface Props {
  nodes?: Node[]
  links?: Link[]
}

const NODE_COLORS: Record<string, string> = {
  SOURCE: 'bg-blue-200 border-blue-400',
  FUSE: 'bg-purple-200 border-purple-400',
  RERANK: 'bg-orange-200 border-orange-400',
  EXPAND: 'bg-teal-200 border-teal-400',
  FILTER: 'bg-red-200 border-red-400',
  BOOST: 'bg-green-200 border-green-400',
  GATE: 'bg-yellow-200 border-yellow-400',
  TRANSFORM: 'bg-indigo-200 border-indigo-400',
  final: 'bg-gray-200 border-gray-400',
}

export default function ProvenanceSankey({ nodes = [], links = [] }: Props) {
  if (nodes.length === 0 || links.length === 0) {
    return <NoData label="No provenance flow data for this query." />
  }

  const maxValue = useMemo(() => Math.max(...links.map((l) => l.value), 1), [links])

  const leftNodes = useMemo(
    () => nodes.filter((n) => !links.some((l) => l.target === n.id) || n.type === 'SOURCE'),
    [nodes, links],
  )
  const rightNodes = useMemo(
    () => nodes.filter((n) => !links.some((l) => l.source === n.id)),
    [nodes, links],
  )
  const middleNodes = useMemo(
    () => nodes.filter((n) => !leftNodes.includes(n) && !rightNodes.includes(n)),
    [nodes, leftNodes, rightNodes],
  )

  const columns = [leftNodes, middleNodes, rightNodes].filter((col) => col.length > 0)

  return (
    <div>
      <SectionHeading title="Candidate provenance flow" />
      <div className="rounded border border-gray-200 bg-white p-4">
        <div className="flex justify-between items-start gap-6 min-w-max">
          {columns.map((col, colIdx) => (
            <div key={colIdx} className="flex flex-col gap-2 min-w-[120px]">
              <div className="text-[10px] text-gray-400 font-medium text-center">
                {colIdx === 0 ? 'Sources' : colIdx === columns.length - 1 ? 'Output' : 'Operators'}
              </div>
              {col.map((node) => {
                const colorClass = NODE_COLORS[node.type || ''] || 'bg-gray-100 border-gray-300'
                const outLinks = links.filter((l) => l.source === node.id)
                const inLinks = links.filter((l) => l.target === node.id)
                const totalOut = outLinks.reduce((s, l) => s + l.value, 0)
                const totalIn = inLinks.reduce((s, l) => s + l.value, 0)
                const count = Math.max(totalOut, totalIn)
                return (
                  <div
                    key={node.id}
                    className={`rounded-lg border-2 px-3 py-2 text-xs ${colorClass}`}
                  >
                    <div className="font-mono font-semibold">{node.label}</div>
                    {count > 0 && (
                      <div className="text-[10px] opacity-70 mt-0.5">
                        {count} candidate{count !== 1 ? 's' : ''}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>

        <div className="mt-3 border-t border-gray-100 pt-2">
          <div className="text-[10px] font-medium text-gray-500 mb-1">Flows</div>
          <div className="flex flex-wrap gap-1">
            {links.map((link, idx) => {
              const widthPx = Math.max(2, (link.value / maxValue) * 40)
              const isDropped = link.dropped
              const isExpanded = link.expanded
              return (
                <div
                  key={`${link.source}:${link.target}:${idx}`}
                  className={`text-[10px] px-2 py-0.5 rounded flex items-center gap-1
                    ${isDropped ? 'bg-red-50 text-red-600 line-through' : isExpanded ? 'bg-teal-50 text-teal-600' : 'bg-gray-50 text-gray-600'}`}
                >
                  <div
                    className={`h-1 rounded ${isDropped ? 'bg-red-300' : isExpanded ? 'bg-teal-300' : 'bg-blue-300'}`}
                    style={{ width: `${widthPx}px` }}
                  />
                  <span>{link.source} → {link.target}</span>
                  <span className="text-gray-400">({link.value})</span>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
