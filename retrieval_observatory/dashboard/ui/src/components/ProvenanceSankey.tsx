import SectionHeading from './SectionHeading'
import NoData from './NoData'

interface Props {
  nodes?: Array<{ id: string; label: string }>
  links?: Array<{ source: string; target: string; value: number }>
}

export default function ProvenanceSankey({ nodes = [], links = [] }: Props) {
  if (nodes.length === 0 || links.length === 0) {
    return <NoData label="No provenance flow data for this query." />
  }

  return (
    <div>
      <SectionHeading title="Provenance flow" />
      <div className="rounded border border-gray-200 bg-white p-3 text-xs">
        <p className="text-gray-600 mb-2">
          Sankey placeholder view. Nodes and links are listed until the full chart renderer is wired.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="font-semibold mb-1">Nodes</div>
            <ul className="space-y-1">
              {nodes.map((n) => (
                <li key={n.id} className="font-mono">{n.label}</li>
              ))}
            </ul>
          </div>
          <div>
            <div className="font-semibold mb-1">Links</div>
            <ul className="space-y-1">
              {links.map((l, idx) => (
                <li key={`${l.source}:${l.target}:${idx}`}>{l.source} → {l.target} ({l.value})</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}
