import { DbSource } from '../api'

interface Props {
  sources: DbSource[]
  activeDbId: string | null
  onSelect: (dbId: string) => void
}

export default function DbTabs({ sources, activeDbId, onSelect }: Props) {
  if (sources.length <= 1) {
    return null
  }

  return (
    <div className="border-b border-gray-200 dark:border-slate-700 px-2 py-2 min-w-[18rem]">
      <p className="text-[10px] uppercase tracking-wide text-gray-400 dark:text-slate-500 px-2 mb-1.5">Databases</p>
      <div className="flex flex-col gap-1">
        {sources.map((src) => {
          const active = src.db_id === activeDbId
          return (
            <button
              key={src.db_id}
              type="button"
              title={src.path}
              onClick={() => onSelect(src.db_id)}
              className={`w-full text-left px-2 py-1.5 rounded-md text-xs transition-colors ${
                active
                  ? 'bg-indigo-100 text-indigo-900 font-medium'
                  : 'text-gray-600 dark:text-slate-300 hover:bg-gray-100'
              }`}
            >
              <span className="block truncate">{src.label}</span>
              <span className="block text-[10px] text-gray-400 dark:text-slate-500 font-normal">
                {src.run_count} run{src.run_count === 1 ? '' : 's'}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
