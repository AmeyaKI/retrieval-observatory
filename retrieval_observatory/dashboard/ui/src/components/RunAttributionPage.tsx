import SegmentOperatorGrid from './SegmentOperatorGrid'
import OperatorInspector from './OperatorInspector'

// Per-stage attribution as its own disclosure level (retobs_finer.md Pillar 1's spine:
// "... → Pipeline architecture → Per-stage attribution → Individual query failures → ...").
// Previously nested inside the "Queries" section; split out so it answers exactly one
// question per page, per the Simplicity principle.
export default function RunAttributionPage({ dbId, runId }: { dbId: string; runId: string }) {
  return (
    <div className="space-y-8">
      <SegmentOperatorGrid dbId={dbId} runId={runId} />
      <OperatorInspector dbId={dbId} runId={runId} />
    </div>
  )
}
