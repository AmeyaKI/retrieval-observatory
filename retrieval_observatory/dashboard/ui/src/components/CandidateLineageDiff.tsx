import { ComparisonEnvelope, JourneySide } from '../api'
import { alignmentLabel, changeGlyph, changeLabel, diffTotals, sideSummary, sortDiffRows } from '../utils/comparisonDiffs'

// Run comparison: one row per paired entity, each side in words, the change as glyph + text.
// Observed differences in recorded journeys only; a changed path is a fact, not an explanation.

function SideCell({ side }: { side: JourneySide | null }) {
  if (!side) {
    return (
      <td className="p-2 text-ink-faint" title="no row in this run">
        —
      </td>
    )
  }
  return (
    <td className="p-2">
      {sideSummary(side)}
      {side.capture_state === 'partial' && <span className="text-ink-muted"> · capture partial</span>}
    </td>
  )
}

function OpList({ title, ids }: { title: string; ids: string[] }) {
  return (
    <div>
      <h4 className="font-medium text-ink">{title}</h4>
      {ids.length === 0 ? (
        <p className="text-ink-muted">none</p>
      ) : (
        <ul className="mt-1 space-y-0.5">
          {ids.map((id) => (
            <li key={id}>
              <code className="font-mono">{id}</code>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

interface Props {
  envelope: ComparisonEnvelope
  onSelectEntity: (entity: string, queryId: string) => void
}

export default function CandidateLineageDiff({ envelope, onSelectEntity }: Props) {
  const { baseline_run_id, candidate_run_id, compatibility, stage_alignment } = envelope.comparison
  const totals = diffTotals(envelope.rows)
  const pairs = envelope.total ?? totals.pairs
  const showQuery = !envelope.scope.query_id
  const rows = sortDiffRows(envelope.rows)

  return (
    <section aria-labelledby="comparison-title" className="app-card space-y-4 p-4 text-sm">
      <div>
        <p className="eyebrow">Comparison</p>
        <h2 id="comparison-title" className="mt-1 font-semibold text-ink">
          Candidate <span className="font-mono">{candidate_run_id}</span> against baseline <span className="font-mono">{baseline_run_id}</span>
        </h2>
        <p className="mt-1 text-xs text-ink-muted">Observed differences in recorded journeys; a changed path is a fact, not an explanation.</p>
      </div>

      {compatibility.corpus_changed ? (
        <div role="status" className="app-inset px-3 py-2 text-xs">
          <span className="font-semibold text-status-warning">matched comparison blocked: corpus changed; showing each run's evidence</span>
        </div>
      ) : compatibility.query_inputs_identical === false ? (
        <div role="status" className="app-inset px-3 py-2 text-xs">
          <span className="font-semibold text-status-warning">
            query inputs differ between the runs; unaligned queries carry no change classification
          </span>
        </div>
      ) : null}
      {compatibility.findings.length > 0 && (
        <details className="app-inset p-3 text-xs">
          <summary className="cursor-pointer font-medium text-ink">Compatibility findings ({compatibility.findings.length})</summary>
          <ul className="mt-2 space-y-1">
            {compatibility.findings.map((finding, index) => (
              <li key={`${finding.code}-${index}`}>
                <span className="font-mono text-ink">{finding.code}</span>
                <span className="text-ink-muted"> — {finding.detail}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="text-xs text-ink-muted">
        {pairs} pairs · {totals.byChange.lost} lost · {totals.byChange.gained} gained · {totals.byChange.rank_changed} rank changed ·{' '}
        {totals.byChange.path_changed} path changed · {totals.captureLimited} evidence-limited
      </p>

      {rows.length === 0 ? (
        <p className="text-ink-muted">No paired rows for this scope.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-xs">
            <caption className="pb-2 text-left text-xs text-ink-muted">Paired journeys, most consequential change first</caption>
            <thead className="bg-surface-muted text-left">
              <tr>
                {showQuery && <th className="p-2">Query</th>}
                <th className="p-2">Entity</th>
                <th className="p-2">Baseline</th>
                <th className="p-2">Candidate</th>
                <th className="p-2">Change</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.query_id}:${row.namespace}:${row.entity_id}`} className="border-t border-slate-200 align-top dark:border-slate-700">
                  {showQuery && <td className="whitespace-nowrap p-2 font-mono">{row.query_id}</td>}
                  <td className="p-2">
                    <button
                      type="button"
                      onClick={() => onSelectEntity(`${row.namespace}:${row.entity_id}`, row.query_id)}
                      className="whitespace-nowrap font-mono text-accent underline-offset-2 hover:underline"
                    >
                      {row.namespace}:{row.entity_id}
                    </button>
                  </td>
                  <SideCell side={row.baseline} />
                  <SideCell side={row.candidate} />
                  <td className="p-2">
                    <span aria-hidden="true">{changeGlyph(row.change)}</span> {changeLabel(row.change)}
                    {row.alignment !== 'aligned' && (
                      <span className="ml-1 rounded border border-slate-200 px-1 text-[10px] text-ink-muted dark:border-slate-700">
                        {alignmentLabel(row.alignment)}
                      </span>
                    )}
                    <div className="text-ink-muted">{row.detail}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {stage_alignment && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-ink">Stage alignment</h3>
          <div className="grid gap-3 text-xs sm:grid-cols-3">
            <div>
              <h4 className="font-medium text-ink">Matched</h4>
              {stage_alignment.matched.length === 0 ? (
                <p className="text-ink-muted">none</p>
              ) : (
                <ul className="mt-1 space-y-0.5">
                  {stage_alignment.matched.map(([baseline, candidate]) => (
                    <li key={`${baseline}↔${candidate}`}>
                      <code className="font-mono">{baseline}</code> ↔ <code className="font-mono">{candidate}</code>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <OpList title="Baseline only" ids={stage_alignment.baseline_only} />
            <OpList title="Candidate only" ids={stage_alignment.candidate_only} />
          </div>
        </div>
      )}
    </section>
  )
}
