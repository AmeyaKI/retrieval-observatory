import { useEffect, useMemo, useState } from 'react'
import {
  CandidateFlow,
  CandidateJourneyRow,
  CandidateJourneys,
  fetchCandidateFlow,
  fetchCandidateJourneys,
} from '../api'
import CandidateMissTable from './CandidateMissTable'
import DocumentPathSimulator from './DocumentPathSimulator'
import StatusPanel from './StatusPanel'
import SectionHeading from './SectionHeading'

function defaultDocId(rows: CandidateJourneyRow[]): string | null {
  const relevantDrop = rows.find((r) => r.relevant && r.dropped_at && !r.survived)
  if (relevantDrop) return relevantDrop.doc_id
  const anyDrop = rows.find((r) => r.dropped_at && !r.survived)
  if (anyDrop) return anyDrop.doc_id
  return rows[0]?.doc_id ?? null
}

/**
 * Hero candidate-flow workspace: path simulator + miss overview table.
 * Used on Query detail and the /candidates/:docId deep link.
 */
export default function CandidateFlowWorkspace({
  dbId,
  runId,
  queryId,
  initialDocId = null,
  syncUrl = false,
}: {
  dbId: string
  runId: string
  queryId: string
  initialDocId?: string | null
  /** When true, selecting a doc updates the hash to .../candidates/:docId */
  syncUrl?: boolean
}) {
  const [journeys, setJourneys] = useState<CandidateJourneys | null>(null)
  const [journeysError, setJourneysError] = useState<string | null>(null)
  const [selectedDocId, setSelectedDocId] = useState<string | null>(initialDocId)
  const [flow, setFlow] = useState<CandidateFlow | null>(null)
  const [flowError, setFlowError] = useState<string | null>(null)

  useEffect(() => {
    setJourneys(null)
    setJourneysError(null)
    fetchCandidateJourneys(dbId, runId, queryId)
      .then((data) => {
        setJourneys(data)
        setSelectedDocId((prev) => {
          if (initialDocId && data.rows.some((r) => r.doc_id === initialDocId)) return initialDocId
          if (prev && data.rows.some((r) => r.doc_id === prev)) return prev
          return defaultDocId(data.rows)
        })
      })
      .catch((e) => setJourneysError(e.message))
  }, [dbId, runId, queryId, initialDocId])

  useEffect(() => {
    if (!selectedDocId) {
      setFlow(null)
      return
    }
    setFlow(null)
    setFlowError(null)
    fetchCandidateFlow(dbId, runId, queryId, selectedDocId)
      .then(setFlow)
      .catch((e) => setFlowError(e.message))
  }, [dbId, runId, queryId, selectedDocId])

  const selectDoc = (docId: string) => {
    setSelectedDocId(docId)
    if (syncUrl) {
      const href = `#/runs/${encodeURIComponent(runId)}/queries/${encodeURIComponent(queryId)}/candidates/${encodeURIComponent(docId)}`
      if (window.location.hash !== href) {
        window.location.hash = href
      }
    }
  }

  const eventDetail = useMemo(() => {
    if (!flow) return null
    return flow.pipelines.map((p) => ({
      pipelineId: p.pipeline_id,
      survived: p.history.survived,
      droppedAt: p.history.dropped_at,
      reason: p.history.dropped_reason,
      assumptions: p.drop_replay_assumptions,
    }))
  }, [flow])

  if (journeysError) {
    return (
      <StatusPanel
        kind="unavailable"
        title="Candidate journeys unavailable"
        message={journeysError}
      />
    )
  }
  if (!journeys) {
    return <StatusPanel kind="loading" message="Loading candidate journeys…" />
  }

  return (
    <section aria-labelledby="candidate-flow-hero-heading" className="space-y-4">
      <div>
        <SectionHeading title="Candidate flow diagnosis" />
        <p id="candidate-flow-hero-heading" className="text-xs text-ink-muted -mt-1">
          Flowchart shows where a selected chunk travels through each stage. The table classifies
          expected vs retrieved chunks (TP / FP / FN / TN over the seen-candidate universe).
        </p>
      </div>

      {flowError && (
        <StatusPanel kind="partial" title="Path simulator partial" message={flowError} />
      )}
      <DocumentPathSimulator flow={flow} />

      <CandidateMissTable
        rows={journeys.rows}
        queryText={journeys.query_text}
        selectedDocId={selectedDocId}
        onSelect={(docId) => selectDoc(docId)}
      />

      {eventDetail && eventDetail.some((d) => d.assumptions) && (
        <details className="text-xs rounded border border-slate-200 dark:border-slate-700 p-3">
          <summary className="cursor-pointer text-ink-muted">
            Replay assumptions for drop operators
          </summary>
          <ul className="mt-2 space-y-2">
            {eventDetail
              .filter((d) => d.assumptions)
              .map((d) => (
                <li key={d.pipelineId}>
                  <span className="font-mono font-semibold">{d.pipelineId}</span>
                  {' · '}
                  strategy <span className="font-mono">{d.assumptions?.strategy}</span>
                  <ul className="list-disc pl-4 text-ink-faint">
                    {(d.assumptions?.caveats ?? []).map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                </li>
              ))}
          </ul>
        </details>
      )}
    </section>
  )
}
