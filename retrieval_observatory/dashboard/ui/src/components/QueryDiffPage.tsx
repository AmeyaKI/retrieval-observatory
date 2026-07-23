import { useEffect, useState } from 'react'
import { CandidateLineageDiffResponse, fetchCandidateLineageDiff } from '../api'
import CandidateLineageDiff from './CandidateLineageDiff'
import StatusPanel from './StatusPanel'

export default function QueryDiffPage({
  dbId,
  runId,
  againstRunId,
  queryId,
  policyPath,
}: {
  dbId: string
  runId: string
  againstRunId: string
  queryId: string
  policyPath?: string
}) {
  const [response, setResponse] = useState<CandidateLineageDiffResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setResponse(null)
    setError(null)
    fetchCandidateLineageDiff(dbId, runId, againstRunId, queryId, policyPath)
      .then(setResponse)
      .catch(e => setError(e.message))
  }, [dbId, runId, againstRunId, queryId, policyPath])

  if (error) return <StatusPanel kind="unavailable" title="Candidate lineage diff unavailable" message={error} />
  if (!response) return <StatusPanel kind="loading" message="Loading evidence-qualified candidate lineage diff…" />
  return <div className="space-y-4"><p className="text-xs text-ink-muted">Query <span className="font-mono">{queryId}</span> — candidate <span className="font-mono">{runId}</span> against baseline <span className="font-mono">{againstRunId}</span>.</p><CandidateLineageDiff response={response} /></div>
}
