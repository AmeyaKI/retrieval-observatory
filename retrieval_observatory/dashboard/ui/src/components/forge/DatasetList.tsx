import { ForgeDataset } from '../../api'
import { DIFFICULTY_ORDER, difficultyBarColor } from '../../utils/difficulty'

interface Props {
  datasets: ForgeDataset[]
  activeId: string | null
  onSelect: (id: string) => void
}

function DifficultyMiniBar({ counts }: { counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  if (!total) return null
  return (
    <div className="flex h-1.5 w-full rounded-full overflow-hidden mt-2" title="Difficulty mix">
      {DIFFICULTY_ORDER.map((d) => {
        const n = counts[d] || 0
        if (!n) return null
        return (
          <div
            key={d}
            style={{ width: `${(n / total) * 100}%`, backgroundColor: difficultyBarColor(d) }}
          />
        )
      })}
    </div>
  )
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return iso
  }
}

export default function DatasetList({ datasets, activeId, onSelect }: Props) {
  if (datasets.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center px-4">
        <p className="text-sm text-gray-400 dark:text-slate-500 text-center">
          No Test Sets yet.<br />
          Run <code className="text-amber-700 bg-amber-50 px-1 rounded">retobs forge run</code> to create one.
        </p>
      </div>
    )
  }
  return (
    <ul className="flex-1 overflow-y-auto p-2 space-y-2">
      {datasets.map((d) => {
        const s = d.summary || {}
        const active = d.dataset_id === activeId
        const corpusName = (d.corpus_path || '').split('/').pop() || d.corpus_path
        return (
          <li key={d.dataset_id}>
            <button
              type="button"
              onClick={() => onSelect(d.dataset_id)}
              className={`w-full text-left rounded-lg border p-3 transition-colors ${
                active ? 'border-amber-300 bg-amber-50' : 'border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-gray-300'
              }`}
            >
              <p className="text-sm font-semibold text-gray-900 dark:text-slate-100 truncate font-mono">{d.dataset_id}</p>
              <p className="text-xs text-gray-400 dark:text-slate-500 truncate mt-0.5">{corpusName} · {formatDate(d.created_at)}</p>
              <p className="text-xs text-gray-500 dark:text-slate-400 mt-1.5">
                <span className="font-medium text-gray-700 dark:text-slate-200">{s.total_scenarios ?? 0}</span> scenarios
                {' · '}
                <span className="font-medium text-gray-700 dark:text-slate-200">{s.total_queries ?? 0}</span> queries
              </p>
              <DifficultyMiniBar counts={s.by_difficulty || {}} />
            </button>
          </li>
        )
      })}
    </ul>
  )
}
