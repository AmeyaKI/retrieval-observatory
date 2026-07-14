import { METRIC_GLOSSARY } from '../utils/metricGlossary'

const SECTIONS: { title: string; keys: (keyof typeof METRIC_GLOSSARY)[] }[] = [
  {
    title: 'Quality metrics',
    keys: ['ndcg', 'recall', 'precision', 'temporal_recall', 'mrr', 'map', 'ref_bm25'],
  },
  {
    title: 'Latency & profiling',
    keys: [
      'latency_p50',
      'latency_p95',
      'latency_p99',
      'latency_percentile_summary',
      'profile_compute_ms',
      'profile_network_ms',
    ],
  },
  {
    title: 'Statistics & stability badges',
    keys: ['ci', 'p_value', 'q_value', 'zero_pct', 'underpowered', 'wide_ci', 'wide_ci_abs', 'high_zero_pct', 'stable'],
  },
  {
    title: 'Pipeline stages & hybrid fusion',
    keys: ['stage', 'arm', 'fused_stage', 'rrf'],
  },
  {
    title: 'Failure labels (per query × pipeline)',
    keys: [
      'failure_labels_intro',
      'candidate_miss',
      'reranker_drop',
      'lexical_mismatch',
      'semantic_mismatch',
      'not_retrieved_by_any_pipeline',
      'qrel_not_in_corpus',
      'corpus_identity_unknown',
      'unstable',
    ],
  },
  {
    title: 'Difficulty labels',
    keys: ['actual_difficulty', 'predicted_difficulty', 'difficulty_diagnostic', 'difficulty_predicted'],
  },
  {
    title: 'Production drift',
    keys: [
      'tracelens_high_churn_threshold',
      'tracelens_error_rate_threshold',
      'tracelens_suspected_rate_threshold',
      'tracelens_latency_p95_threshold',
      'psi',
      'ks_test',
      'tracelens_drift_thresholds',
    ],
  },
  {
    title: 'Findings',
    keys: ['reliability_components'],
  },
]

function labelForKey(key: string): string {
  return key.replace(/_/g, ' ')
}

export default function GlossaryWorkspace() {
  const used = new Set(SECTIONS.flatMap((s) => s.keys))

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-3xl mx-auto">
        <header className="mb-6">
          <p className="text-xs uppercase tracking-wide text-gray-400 dark:text-slate-500">Reference</p>
          <h1 className="text-xl font-bold text-gray-900 dark:text-slate-100">Glossary</h1>
          <p className="text-sm text-gray-600 dark:text-slate-300 mt-1">
            How to read metrics, labels, evidence classes, and status badges across Runs, Compare, Queries, Production, and Test Sets.
          </p>
        </header>

        <section className="mb-8 rounded-lg border border-indigo-200 bg-indigo-50/50 p-4 text-sm text-indigo-900">
          <h2 className="font-semibold mb-2">Color convention</h2>
          <p>
            Emerald = good / winner · Amber = caution · Rose = regression or failure · Slate/gray = neutral or
            insufficient data.
          </p>
          <p className="mt-2">
            Diagnostic buckets are post-hoc benchmark outcomes; predicted difficulty is pre-retrieval from query text.
            Suspected production failures are label-free proxy signals — not measured Recall.
          </p>
        </section>

        {SECTIONS.map((section) => (
          <section key={section.title} className="mb-8">
            <h2 className="text-base font-semibold text-gray-800 dark:text-slate-100 mb-3">{section.title}</h2>
            <dl className="space-y-3">
              {section.keys.map((key) => (
                <div key={key} className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-3">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">{labelForKey(key)}</dt>
                  <dd className="text-sm text-gray-700 dark:text-slate-200 mt-1 leading-relaxed">{METRIC_GLOSSARY[key]}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}

        <section className="mb-8">
          <h2 className="text-base font-semibold text-gray-800 dark:text-slate-100 mb-3">Other</h2>
          <dl className="space-y-3">
            {Object.keys(METRIC_GLOSSARY)
              .filter((key) => !used.has(key as keyof typeof METRIC_GLOSSARY))
              .map((key) => (
                <div key={key} className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-3">
                  <dt className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">{labelForKey(key)}</dt>
                  <dd className="text-sm text-gray-700 dark:text-slate-200 mt-1 leading-relaxed">
                    {METRIC_GLOSSARY[key as keyof typeof METRIC_GLOSSARY]}
                  </dd>
                </div>
              ))}
          </dl>
        </section>
      </div>
    </div>
  )
}
