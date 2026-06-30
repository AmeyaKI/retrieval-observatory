import type { DemoContext } from '../api'

interface Props {
  context: DemoContext
  onOpenTour: () => void
}

export default function DemoQuickLinks({ context, onOpenTour }: Props) {
  const lineageHref = context.sample_query_id
    ? `#/query/${encodeURIComponent(context.sample_query_id)}`
    : null

  return (
    <div className="shrink-0 border-b border-indigo-200 bg-gradient-to-r from-indigo-50 via-amber-50/80 to-teal-50 px-4 py-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-700">
      <span className="font-semibold text-indigo-900">Demo dataset</span>
      <span className="text-gray-500">
        baseline <span className="font-mono">{context.experiment_names?.baseline ?? context.baseline_run_id}</span>
        {' vs '}
        candidate <span className="font-mono">{context.experiment_names?.candidate ?? context.candidate_run_id}</span>
      </span>
      <span className="flex flex-wrap items-center gap-3 ml-auto">
        <button
          type="button"
          onClick={onOpenTour}
          className="text-indigo-700 hover:text-indigo-900 underline decoration-indigo-300"
        >
          Platform tour
        </button>
        <a href="#/benchmarks" className="text-indigo-700 hover:text-indigo-900 underline decoration-indigo-300">
          Compare runs
        </a>
        {context.forge_dataset_id && (
          <a
            href={`#/forge/${encodeURIComponent(context.forge_dataset_id)}`}
            className="text-amber-800 hover:text-amber-900 underline decoration-amber-300"
          >
            Forge dataset
          </a>
        )}
        {context.tracelens_service && (
          <a
            href={`#/tracelens/${encodeURIComponent(context.tracelens_service)}`}
            className="text-teal-800 hover:text-teal-900 underline decoration-teal-300"
          >
            TraceLens
          </a>
        )}
        <a href="#/advisor" className="text-violet-700 hover:text-violet-900 underline decoration-violet-300">
          Advisor
        </a>
        {lineageHref && (
          <a href={lineageHref} className="text-gray-800 hover:text-gray-950 underline decoration-gray-400 font-medium">
            Query lineage
          </a>
        )}
        <a href="#/glossary" className="text-gray-600 hover:text-gray-800 underline decoration-gray-300">
          Glossary
        </a>
      </span>
    </div>
  )
}
