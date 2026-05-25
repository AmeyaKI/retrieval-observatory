import { Run } from '../api'

interface Props {
  runs: Run[]
  selectedIds: string[]
  onToggle: (runId: string) => void
}

function formatDate(iso: string | null): string {
  if (!iso) return 'running...'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function RunsSidebar({ runs, selectedIds, onToggle }: Props) {
  if (runs.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-sm text-gray-400">No runs yet</p>
      </div>
    )
  }

  return (
    <ul className="flex-1 overflow-y-auto divide-y divide-gray-100">
      {runs.map((run) => {
        const selected = selectedIds.includes(run.run_id)
        return (
          <li
            key={run.run_id}
            onClick={() => onToggle(run.run_id)}
            className={`px-4 py-3 cursor-pointer hover:bg-gray-50 transition-colors ${
              selected ? 'bg-indigo-50 border-l-2 border-indigo-500' : ''
            }`}
          >
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={selected}
                onChange={() => onToggle(run.run_id)}
                onClick={(e) => e.stopPropagation()}
                className="accent-indigo-600"
              />
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900 truncate">
                  {run.experiment_name}
                </p>
                <p className="text-xs text-gray-500 font-mono">{run.run_id}</p>
                <p className="text-xs text-gray-400">{formatDate(run.started_at)}</p>
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
