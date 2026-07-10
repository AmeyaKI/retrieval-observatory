import { useEffect, useState } from 'react'
import { CandidateFlow, fetchCandidateFlow } from '../api'
import ProvenanceSankey from './ProvenanceSankey'
import NoData from './NoData'

interface SankeyNode {
  id: string
  label: string
  type?: string
}

interface SankeyLink {
  source: string
  target: string
  value: number
  dropped?: boolean
  expanded?: boolean
}

function toSankey(flow: CandidateFlow): { nodes: SankeyNode[]; links: SankeyLink[] } {
  const nodes = new Map<string, SankeyNode>()
  const links = new Map<string, SankeyLink>()
  const addNode = (id: string, label: string, type?: string) => {
    if (!nodes.has(id)) nodes.set(id, { id, label, type })
  }
  const addLink = (source: string, target: string, dropped: boolean, expanded: boolean) => {
    const key = `${source}:${target}`
    const existing = links.get(key)
    if (existing) {
      existing.value += 1
      existing.dropped = existing.dropped || dropped
      existing.expanded = existing.expanded || expanded
    } else {
      links.set(key, { source, target, value: 1, dropped, expanded })
    }
  }

  for (const pipeline of flow.pipelines) {
    let prev = 'query'
    addNode('query', 'Query')
    for (const event of pipeline.history.events) {
      addNode(event.op_id, event.op_name, event.op_type)
      addLink(prev, event.op_id, event.event === 'dropped', event.event === 'introduced' && prev !== 'query')
      prev = event.op_id
    }
    const finalId = pipeline.history.survived ? 'final' : `dropped:${pipeline.trace_id}`
    addNode(finalId, pipeline.history.survived ? 'Final result' : 'Dropped', 'final')
    addLink(prev, finalId, !pipeline.history.survived, false)
  }

  return { nodes: Array.from(nodes.values()), links: Array.from(links.values()) }
}

// Candidate provenance flow (Item C): a visual Sankey companion to CandidateFlowPanel's
// textual event list, showing one document's aggregate journey across every pipeline that
// ran this query -- where it was introduced, promoted, or dropped, and by which operator.
export default function RunCandidateFlowPage({
  dbId,
  runId,
  queryId,
  docId,
}: {
  dbId: string
  runId: string
  queryId: string
  docId: string
}) {
  const [flow, setFlow] = useState<CandidateFlow | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setFlow(null)
    setError(null)
    fetchCandidateFlow(dbId, runId, queryId, docId)
      .then(setFlow)
      .catch((e) => setError(e.message))
  }, [dbId, runId, queryId, docId])

  if (error) return <NoData label={error} />
  if (!flow) {
    return (
      <div className="flex items-center gap-2 text-ink-faint text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 dark:border-slate-600 border-t-indigo-600" />
        Loading candidate flow...
      </div>
    )
  }

  const { nodes, links } = toSankey(flow)

  return (
    <div className="space-y-2">
      <p className="text-xs text-ink-muted">
        Document <span className="font-mono">{docId}</span> across query <span className="font-mono">{queryId}</span>
      </p>
      <ProvenanceSankey nodes={nodes} links={links} />
    </div>
  )
}
