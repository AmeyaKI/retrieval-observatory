import { DemoContext } from '../api'

export default function HomeWorkspace({ context }: { context?: DemoContext | null }) {
  const runHref = context?.baseline_run_id
    ? `#/runs/${encodeURIComponent(context.baseline_run_id)}`
    : '#/runs'
  return (
    <main className="flex-1 overflow-auto p-6 sm:p-10" aria-labelledby="home-title">
      <div className="mx-auto max-w-5xl">
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Retrieval reliability workspace</p>
        <h1 id="home-title" className="mt-2 text-3xl font-semibold text-ink">Find where retrieval fails, then verify the fix.</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-ink-muted">
          Evaluate a pipeline, compare an explicit baseline and candidate, and follow affected queries to the exact operator and candidate transition.
        </p>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[
            ['Runs', 'Review a conclusion, evidence health, affected queries, and next action.', runHref],
            ['Compare', 'Gate decisions on corpus, qrel, label, effect, power, and paired evidence.', '#/compare'],
            ['Queries', 'Trace query ground truth and candidate movement across operators.', '#/queries'],
            ['Production', 'Investigate sampled production traces, hotspots, and drift evidence.', '#/production'],
            ['Test Sets', 'Generate and validate corpus stress tests with explicit provenance.', '#/test-sets'],
          ].map(([title, description, href]) => (
            <a key={title} href={href} className="rounded-xl border border-slate-300 dark:border-slate-700 bg-surface p-5 hover:border-indigo-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600">
              <h2 className="font-semibold text-ink">{title}</h2>
              <p className="mt-2 text-sm leading-5 text-ink-muted">{description}</p>
              <span className="mt-4 inline-block text-sm font-medium text-indigo-700 dark:text-indigo-300">Open {title} →</span>
            </a>
          ))}
        </div>
      </div>
    </main>
  )
}
