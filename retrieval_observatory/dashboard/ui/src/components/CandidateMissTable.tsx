import { useMemo, useState } from 'react'
import { CandidateJourneyRow } from '../api'
import {
  CONFUSION_META,
  ConfusionLabel,
  confusionLabel,
  countConfusion,
} from '../utils/confusion'

type FilterMode = 'all' | ConfusionLabel

export default function CandidateMissTable({
  rows,
  queryText,
  selectedDocId,
  onSelect,
}: {
  rows: CandidateJourneyRow[]
  queryText?: string | null
  selectedDocId: string | null
  onSelect: (docId: string, pipelineId: string) => void
}) {
  const [filter, setFilter] = useState<FilterMode>('all')
  const counts = useMemo(() => countConfusion(rows), [rows])

  const filtered = useMemo(() => {
    if (filter === 'all') return rows
    return rows.filter((row) => confusionLabel(row) === filter)
  }, [rows, filter])

  return (
    <div className="space-y-2" id="candidate-miss-table">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-ink">Expected vs retrieved chunks</h3>
          <p className="text-xs text-ink-muted mt-0.5">
            Seen-candidate universe for this query
            {queryText ? (
              <>
                : <span className="italic text-ink">{queryText}</span>
              </>
            ) : null}
            . Click a row to animate that chunk on the flowchart above.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={() => setFilter('all')}
          className={`rounded border px-2 py-1 text-[11px] ${
            filter === 'all'
              ? 'border-indigo-400 bg-indigo-50 text-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-200'
              : 'border-slate-200 dark:border-slate-700 text-ink-muted'
          }`}
        >
          All ({rows.length})
        </button>
        {(['TP', 'FP', 'FN', 'TN'] as const).map((label) => (
          <button
            key={label}
            type="button"
            onClick={() => setFilter(label)}
            className={`rounded border px-2 py-1 text-[11px] ${
              filter === label
                ? CONFUSION_META[label].className + ' ring-1 ring-indigo-400'
                : CONFUSION_META[label].className + ' opacity-80'
            }`}
            title={CONFUSION_META[label].short}
          >
            {label} · {counts[label]}
            <span className="ml-1 hidden sm:inline text-[10px] opacity-80">
              {CONFUSION_META[label].short}
            </span>
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <p className="text-xs text-ink-faint rounded border border-dashed border-slate-200 dark:border-slate-700 p-3">
          No chunks match this filter.
        </p>
      ) : (
        <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="bg-surface-muted text-ink-faint">
              <tr>
                <th className="p-2 font-medium">Type</th>
                <th className="p-2 font-medium">Chunk preview</th>
                <th className="p-2 font-medium">Pipeline</th>
                <th className="p-2 font-medium">Outcome</th>
                <th className="p-2 font-medium">Lost at</th>
                <th className="p-2 font-medium">Reason</th>
                <th className="p-2 font-medium">Rank</th>
                <th className="p-2 font-medium">Doc ID</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => {
                const selected = selectedDocId === row.doc_id
                const label = confusionLabel(row)
                const meta = CONFUSION_META[label]
                return (
                  <tr
                    key={`${row.pipeline_id}:${row.doc_id}`}
                    className={`border-t border-slate-200 dark:border-slate-700 cursor-pointer ${
                      selected
                        ? 'bg-indigo-50/80 dark:bg-indigo-950/30'
                        : 'hover:bg-slate-50 dark:hover:bg-slate-800/40'
                    }`}
                    onClick={() => onSelect(row.doc_id, row.pipeline_id)}
                  >
                    <td className="p-2">
                      <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${meta.className}`}>
                        {label}
                      </span>
                    </td>
                    <td className="p-2 max-w-[18rem]">
                      <p className="text-ink leading-snug line-clamp-2" title={row.doc_preview ?? undefined}>
                        {row.doc_preview?.trim() || (
                          <span className="text-ink-faint italic">No preview available</span>
                        )}
                      </p>
                      {row.relevant && (
                        <span className="text-[10px] text-emerald-700 dark:text-emerald-300">
                          expected relevant{row.grade != null ? ` · grade ${row.grade}` : ''}
                        </span>
                      )}
                    </td>
                    <td className="p-2 font-mono text-[11px]">{row.pipeline_id}</td>
                    <td className="p-2">
                      {row.survived
                        ? 'returned'
                        : row.dropped_at
                          ? 'filtered'
                          : row.relevant
                            ? 'never retrieved'
                            : 'excluded'}
                    </td>
                    <td className="p-2 font-mono">{row.dropped_at ?? '—'}</td>
                    <td className="p-2 max-w-[10rem]">
                      <span className="line-clamp-2">{row.drop_reason ?? row.miss_type ?? '—'}</span>
                      {row.drop_reason_inferred ? (
                        <span className="ml-1 text-[10px] text-ink-faint">(inferred)</span>
                      ) : null}
                    </td>
                    <td className="p-2 font-mono">{row.final_rank ?? '—'}</td>
                    <td className="p-2 font-mono text-[10px] text-ink-faint">{row.doc_id}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
