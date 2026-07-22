import {
  CandidateLineageDiffEntry,
  CandidateLineageDiffResponse,
  CandidateLineageEdge,
  CandidateLineageGraphSnapshot,
  CandidateLineageNode,
} from '../api'
import CandidateLineageGraph from './CandidateLineageGraph'
import StatusPanel from './StatusPanel'

function graphProps(graph: CandidateLineageGraphSnapshot): { nodes: CandidateLineageNode[]; edges: CandidateLineageEdge[] } {
  const nodes = Object.values(graph.candidates).map(candidate => ({
    ...candidate,
    node_id: `${graph.trace_id}:${candidate.candidate_id}`,
    trace_id: graph.trace_id,
    pipeline_id: graph.pipeline_id,
  }))
  const edges = graph.edges.map(edge => ({
    ...edge,
    trace_id: graph.trace_id,
    pipeline_id: graph.pipeline_id,
    source_node_id: `${graph.trace_id}:${edge.source_candidate_id}`,
    target_node_id: `${graph.trace_id}:${edge.target_candidate_id}`,
  }))
  return { nodes, edges }
}

function Side({ title, graph }: { title: string; graph: CandidateLineageGraphSnapshot }) {
  const props = graphProps(graph)
  return <div className="min-w-0 space-y-2"><h4 className="text-xs font-semibold">{title}</h4><CandidateLineageGraph {...props} selectedNodeId={null} onSelect={() => undefined} /></div>
}

function BlockedDiff({ diff }: { diff: CandidateLineageDiffEntry }) {
  return <div className="space-y-3"><ul className="list-disc pl-5 text-xs text-ink-muted">{diff.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul><div className="grid gap-4 lg:grid-cols-2"><Side title="Baseline recorded path" graph={diff.baseline} /><Side title="Candidate recorded path" graph={diff.candidate} /></div></div>
}

export default function CandidateLineageDiff({ response }: { response: CandidateLineageDiffResponse }) {
  const blocked = response.readiness.status !== 'READY'
  return <section aria-labelledby="candidate-lineage-diff-heading" className="space-y-4">
    <div><p className="text-xs uppercase tracking-wide text-ink-muted">Lineage diff</p><h2 id="candidate-lineage-diff-heading" className="text-xl font-bold">{response.readiness.status}</h2><p className="text-xs text-ink-muted">Observed path differences only; route changes do not establish cause.</p></div>
    {response.readiness.findings.map(finding => <StatusPanel key={finding.code} kind={finding.status === 'BLOCK' ? 'invalid' : 'partial'} title={finding.code} message={<><span>{finding.detail}</span> <span>{finding.next_action}</span></>} />)}
    {response.diffs.length === 0 ? <StatusPanel kind="unavailable" title="No aligned pipeline pair" message="The selected runs have no pipeline identity in common for this query." /> : response.diffs.map((diff, index) => <div key={`${diff.baseline.trace_id}:${diff.candidate.trace_id}:${index}`} className="rounded border border-slate-200 dark:border-slate-700 p-3 space-y-3"><h3 className="font-mono text-sm font-semibold">{diff.candidate.pipeline_id}</h3>{blocked || diff.status !== 'READY' ? <BlockedDiff diff={diff} /> : diff.changed.length === 0 ? <p className="text-xs text-ink-muted">No observed candidate-path changes for aligned identities.</p> : <div className="overflow-x-auto"><table className="min-w-full text-xs"><thead className="bg-surface-muted text-left"><tr><th className="p-2">Change</th><th className="p-2">Logical chunk</th><th className="p-2">Document revision/hash</th><th className="p-2">Observed detail</th></tr></thead><tbody>{diff.changed.map((change, changeIndex) => <tr key={`${change.logical_chunk_id}:${change.kind}:${changeIndex}`} className="border-t border-slate-200 dark:border-slate-700"><td className="p-2 font-semibold">{change.kind.replace(/_/g, ' ')}</td><td className="p-2 font-mono">{change.logical_chunk_id}</td><td className="p-2 font-mono">{change.document_identity}</td><td className="p-2">{change.detail}</td></tr>)}</tbody></table></div>}</div>)}
  </section>
}
