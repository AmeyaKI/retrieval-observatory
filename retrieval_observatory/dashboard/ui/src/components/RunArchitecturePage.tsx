import PipelineDagView from './PipelineDagView'

export default function RunArchitecturePage({ dbId, runId }: { dbId: string; runId: string }) {
  return (
    <div>
      <p className="text-xs text-ink-muted mb-3">
        Directed graph — parallel branches, merge points, per-node quality with bootstrap CIs.
      </p>
      <PipelineDagView dbId={dbId} runId={runId} />
    </div>
  )
}
