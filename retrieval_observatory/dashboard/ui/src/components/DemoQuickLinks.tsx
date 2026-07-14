import type { DemoContext } from '../api'

interface Props {
  context: DemoContext
  onOpenTour: () => void
}

export default function DemoQuickLinks({ context, onOpenTour }: Props) {
  const lineageHref = context.sample_query_id
    ? `#/queries/${encodeURIComponent(context.sample_query_id)}`
    : null

  return (
    <div className="shrink-0 border-b border-indigo-200 bg-gradient-to-r from-indigo-50 via-amber-50/80 to-teal-50 px-4 py-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-700 dark:text-slate-200">
      <span className="font-semibold text-indigo-900">Demo dataset</span>
      <span className="text-gray-500 dark:text-slate-400">
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
          Workflow tour
        </button>
        <a href="#/compare" className="text-indigo-700 hover:text-indigo-900 underline decoration-indigo-300">
          Compare runs
        </a>
        {context.validation_run_id && (
          <a href={`#/runs/${encodeURIComponent(context.validation_run_id)}`} className="text-indigo-700 hover:text-indigo-900 underline decoration-indigo-300">
            Validated fix
          </a>
        )}
        {context.forge_dataset_id && (
          <a
            href={`#/test-sets/${encodeURIComponent(context.forge_dataset_id)}`}
            className="text-amber-800 hover:text-amber-900 underline decoration-amber-300"
          >
            Test Set
          </a>
        )}
        {context.tracelens_service && (
          <a
            href={`#/production/${encodeURIComponent(context.tracelens_service)}`}
            className="text-teal-800 hover:text-teal-900 underline decoration-teal-300"
          >
            Production
          </a>
        )}
        <a href="#/runs" className="text-violet-700 hover:text-violet-900 underline decoration-violet-300">
          Findings
        </a>
        {lineageHref && (
          <a href={lineageHref} className="text-gray-800 dark:text-slate-100 hover:text-gray-950 underline decoration-gray-400 font-medium">
            Query lineage
          </a>
        )}
        <a href="#/glossary" className="text-gray-600 dark:text-slate-300 hover:text-gray-800 underline decoration-gray-300">
          Glossary
        </a>
      </span>
    </div>
  )
}
