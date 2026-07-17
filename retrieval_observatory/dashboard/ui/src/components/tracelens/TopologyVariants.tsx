import { useEffect, useState } from 'react'
import { fetchTopologyVariants, TopologyVariant } from '../../api'

export default function TopologyVariants({ dbId, service }: { dbId: string; service: string }) {
  const [items, setItems] = useState<TopologyVariant[] | null>(null)
  const [search, setSearch] = useState('')
  useEffect(() => { fetchTopologyVariants(dbId, service).then(page => setItems(page.items)) }, [dbId, service])
  const shown = (items ?? []).filter(item => JSON.stringify(item).toLowerCase().includes(search.toLowerCase()))
  return <div>
    <label className="text-xs text-ink-muted">Search architecture <input value={search} onChange={event => setSearch(event.target.value)} className="ml-2 border rounded px-2 py-1" /></label>
    <div className="mt-3 space-y-2">{shown.map((item, index) => <div key={item.topology_hash ?? item.variant_id ?? index} className="border rounded p-3 text-xs">
      <div className="font-mono">{item.topology_hash ?? item.variant_id ?? 'default'}</div>
      <div className="text-ink-muted">{item.trace_count ?? item.count ?? 0} traces · {(item.operator_ids ?? []).join(' → ') || 'operator list unavailable'}</div>
    </div>)}</div>
  </div>
}
