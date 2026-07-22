import { useEffect, useMemo, useState } from 'react'
import {
  CandidateFlow,
  CandidateJourneyRow,
  CandidateJourneys,
  CandidateLineageResponse,
  fetchCandidateFlow,
  fetchCandidateJourneys,
  fetchCandidateLineage,
} from '../api'
import CandidateLineageGraph from './CandidateLineageGraph'
import CandidateMissTable from './CandidateMissTable'
import CandidatePassport from './CandidatePassport'
import DocumentPathSimulator from './DocumentPathSimulator'
import StageLossAccounting from './StageLossAccounting'
import StatusPanel from './StatusPanel'
import SectionHeading from './SectionHeading'

function defaultDocId(rows: CandidateJourneyRow[]): string | null {
  const diagnostic = rows.find(row => row.outcome && !['relevant_retained', 'irrelevant_removed'].includes(row.outcome))
  return diagnostic?.doc_id ?? rows[0]?.doc_id ?? null
}

export default function CandidateFlowWorkspace({
  dbId, runId, queryId, initialDocId = null, syncUrl = false,
}: {
  dbId: string; runId: string; queryId: string; initialDocId?: string | null; syncUrl?: boolean
}) {
  const [journeys, setJourneys] = useState<CandidateJourneys | null>(null)
  const [lineage, setLineage] = useState<CandidateLineageResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedDocId, setSelectedDocId] = useState<string | null>(initialDocId)
  const [flow, setFlow] = useState<CandidateFlow | null>(null)
  const [flowError, setFlowError] = useState<string | null>(null)

  useEffect(() => {
    setJourneys(null); setLineage(null); setError(null)
    Promise.all([fetchCandidateJourneys(dbId, runId, queryId), fetchCandidateLineage(dbId, runId, queryId)])
      .then(([journeyData, lineageData]) => {
        setJourneys(journeyData); setLineage(lineageData)
        const requested = initialDocId ?? defaultDocId(journeyData.rows)
        const node = lineageData.graph.nodes.find(item => item.candidate_id === requested) ?? lineageData.graph.nodes[0]
        setSelectedNodeId(node?.node_id ?? null); setSelectedDocId(node?.candidate_id ?? requested)
      })
      .catch(e => setError(e.message))
  }, [dbId, runId, queryId, initialDocId])

  useEffect(() => {
    if (!selectedDocId) { setFlow(null); return }
    setFlow(null); setFlowError(null)
    fetchCandidateFlow(dbId, runId, queryId, selectedDocId).then(setFlow).catch(e => setFlowError(e.message))
  }, [dbId, runId, queryId, selectedDocId])

  const selectedCandidate = lineage?.graph.nodes.find(node => node.node_id === selectedNodeId) ?? null
  const eventDetail = useMemo(() => flow?.pipelines.map(pipeline => ({ pipelineId: pipeline.pipeline_id, assumptions: pipeline.drop_replay_assumptions })) ?? [], [flow])

  const selectNode = (nodeId: string) => {
    const node = lineage?.graph.nodes.find(item => item.node_id === nodeId)
    if (!node) return
    setSelectedNodeId(nodeId); setSelectedDocId(node.candidate_id)
    if (syncUrl) window.location.hash = `#/runs/${encodeURIComponent(runId)}/queries/${encodeURIComponent(queryId)}/candidates/${encodeURIComponent(node.candidate_id)}`
  }

  const selectJourney = (docId: string, pipelineId: string, traceId: string) => {
    const node = lineage?.graph.nodes.find(item => item.candidate_id === docId && item.pipeline_id === pipelineId && item.trace_id === traceId)
      ?? lineage?.graph.nodes.find(item => item.candidate_id === docId)
    if (node) selectNode(node.node_id)
  }

  if (error) return <StatusPanel kind="unavailable" title="Candidate lineage unavailable" message={error} />
  if (!journeys || !lineage) return <StatusPanel kind="loading" message="Loading recorded candidate lineage…" />

  return <section aria-labelledby="candidate-flow-hero-heading" className="space-y-5">
    <div><SectionHeading title="Candidate lineage explorer" /><p id="candidate-flow-hero-heading" className="text-xs text-ink-muted -mt-1">Inspect the static recorded DAG, evidence-aware outcomes, stage counts, and trace-qualified candidate passport.</p></div>
    {lineage.readiness.status !== 'READY' ? <StatusPanel kind="partial" title={`Lineage diagnosis · ${lineage.readiness.status}`} message="The selected capture cannot support every lineage claim. Unknown and partial states remain explicit below." /> : null}
    <CandidateLineageGraph nodes={lineage.graph.nodes} edges={lineage.graph.edges} selectedNodeId={selectedNodeId} onSelect={selectNode} />
    <StageLossAccounting accounting={lineage.accounting} />
    <CandidateMissTable rows={journeys.rows} queryText={journeys.query_text} selectedDocId={selectedDocId} onSelect={selectJourney} />
    <CandidatePassport candidate={selectedCandidate} />
    <details className="rounded border border-slate-200 dark:border-slate-700 p-3">
      <summary className="cursor-pointer text-sm font-semibold">Replay recorded transitions</summary>
      <div className="mt-3 space-y-3">
        {flowError ? <StatusPanel kind="partial" title="Recorded replay partial" message={flowError} /> : null}
        <DocumentPathSimulator flow={flow} />
        {eventDetail.some(detail => detail.assumptions) ? <details className="text-xs"><summary className="cursor-pointer text-ink-muted">Replay assumptions for legacy drop operators</summary><ul className="mt-2 space-y-2">{eventDetail.filter(detail => detail.assumptions).map(detail => <li key={detail.pipelineId}><span className="font-mono font-semibold">{detail.pipelineId}</span> · strategy <span className="font-mono">{detail.assumptions?.strategy}</span><ul className="list-disc pl-4 text-ink-faint">{(detail.assumptions?.caveats ?? []).map(caveat => <li key={caveat}>{caveat}</li>)}</ul></li>)}</ul></details> : null}
      </div>
    </details>
  </section>
}
