import { Run, selectionKey } from '../api'

interface Props {
  runs: Run[]
  selectedKeys: Set<string>
  activeDbId: string | null
  onToggle: (dbId: string, runId: string) => void
}

function formatDate(iso: string | null): string {
  if (!iso) return 'running...'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function RunsSidebar({ runs, selectedKeys, activeDbId, onToggle }: Props) {
  if (!activeDbId) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-sm text-gray-400 dark:text-slate-500">No database selected</p>
      </div>
    )
  }

  if (runs.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center px-4">
        <p className="text-sm text-gray-400 dark:text-slate-500 text-center">No runs in this database</p>
      </div>
    )
  }

  const selectedCount = selectedKeys.size

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="px-4 py-2 border-b border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-800/60 min-w-[18rem]">
        {selectedCount === 0 && (
          <p className="text-xs text-gray-400 dark:text-slate-500">Click a run to explore it · Check two to compare</p>
        )}
        {selectedCount === 1 && (
          <p className="text-xs text-ink-muted font-medium">1 run selected — viewing details</p>
        )}
        {selectedCount >= 2 && (
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-indigo-700 bg-indigo-50 border border-indigo-200 rounded px-2 py-0.5">
              {selectedCount} runs selected
            </span>
            <span className="text-xs text-gray-400 dark:text-slate-500">— comparing</span>
          </div>
        )}
      </div>
      <ul className="flex-1 overflow-y-auto divide-y divide-gray-100">
        {runs.map((run) => {
          const dbId = run.db_id ?? activeDbId
          const key = selectionKey({ dbId, runId: run.run_id })
          const selected = selectedKeys.has(key)
          return (
            <li
              key={key}
              className={`hover:bg-gray-50 transition-colors ${
                selected ? 'bg-indigo-50 border-l-2 border-indigo-500' : ''
              }`}
            >
              <label className="flex cursor-pointer items-start gap-2 px-4 py-3">
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={() => onToggle(dbId, run.run_id)}
                  className="accent-indigo-600 mt-0.5 shrink-0"
                />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-900 dark:text-slate-100 truncate flex items-center gap-1.5">
                    <span className="truncate">{run.experiment_name}</span>
                    {run.golden_set && (
                      <span className="shrink-0 text-[10px] font-medium uppercase tracking-wide px-1 py-0.5 rounded bg-amber-100 text-amber-800">
                        golden
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-ink-muted font-mono truncate">{run.run_id}</p>
                  <p className="text-xs text-gray-400 dark:text-slate-500">{formatDate(run.started_at)}</p>
                </div>
              </label>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
