import CandidateFlowWorkspace from './CandidateFlowWorkspace'

/** Deep-link page for a selected document — same hero workspace as Query detail. */
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
  return (
    <div className="space-y-4">
      <a
        href={`#/runs/${encodeURIComponent(runId)}/queries/${encodeURIComponent(queryId)}`}
        className="text-xs text-indigo-700 dark:text-indigo-300 hover:underline"
      >
        ← Back to query {queryId}
      </a>
      <CandidateFlowWorkspace
        dbId={dbId}
        runId={runId}
        queryId={queryId}
        initialDocId={docId}
        syncUrl
      />
    </div>
  )
}
