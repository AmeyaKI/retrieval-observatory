import SegmentOperatorGrid from './SegmentOperatorGrid'

// Per-stage attribution as its own disclosure level (retobs_finer.md Pillar 1's spine:
// "... → Pipeline architecture → Per-stage attribution → Individual query failures → ...").
// Previously nested inside the "Queries" section; split out so it answers exactly one
// question per page, per the Simplicity principle. The operator inspector moved to
// Investigate, where it reads the investigation envelopes (attribution is retired).
export default function RunAttributionPage({ dbId, runId }: { dbId: string; runId: string }) {
  return (
    <div className="space-y-8">
      <SegmentOperatorGrid dbId={dbId} runId={runId} />
    </div>
  )
}
