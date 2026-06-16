import { useEffect, useMemo, useState } from 'react'
import {
  fetchForgeDataset,
  fetchForgeQueries,
  fetchForgeDatasetRuns,
  ForgeDatasetDetail,
  ForgeQuery,
  ForgeRunRef,
  ForgeScenario,
} from '../../api'
import { DIFFICULTY_ORDER, difficultyChipClass, difficultyBarColor } from '../../utils/difficulty'

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <div className="mb-3">
        <h2 className="text-base font-semibold text-gray-800">{title}</h2>
        {subtitle && <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </section>
  )
}

function DistributionBars({ counts, colorFor }: { counts: Record<string, number>; colorFor?: (k: string) => string }) {
  const entries = Object.entries(counts)
  const total = entries.reduce((a, [, n]) => a + n, 0) || 1
  if (!entries.length) return <p className="text-xs text-gray-400">No data</p>
  return (
    <div className="space-y-1.5">
      {entries.map(([k, n]) => (
        <div key={k} className="flex items-center gap-2 text-xs">
          <span className="w-24 shrink-0 text-gray-600 capitalize">{k}</span>
          <div className="flex-1 bg-gray-100 rounded-full h-2.5 overflow-hidden">
            <div
              className="h-full rounded-full"
              style={{ width: `${(n / total) * 100}%`, backgroundColor: colorFor ? colorFor(k) : '#6366f1' }}
            />
          </div>
          <span className="w-10 text-right tabular-nums text-gray-700 font-medium">{n}</span>
        </div>
      ))}
    </div>
  )
}

function LabelTrustBanner({ coverage }: { coverage: number }) {
  const pct = Math.round(coverage * 100)
  const validated = pct > 0
  return (
    <div className={`rounded-lg border p-3 text-xs ${validated ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50'}`}>
      <p className="font-semibold text-gray-800 mb-0.5">Ground-truth provenance</p>
      <p className="text-gray-700 leading-relaxed">
        Relevance labels are <strong>extractive</strong> — each query's source document is graded relevant (grade&nbsp;2).
        {validated
          ? ` An LLM validation pass expanded/confirmed labels for ${pct}% of queries.`
          : ' No LLM validation pass was run, so labels are extractive-only (no expansion to other relevant docs).'}
      </p>
      <p className="text-gray-500 mt-1">
        Treat stress scores as a <strong>lower bound</strong>: a pipeline may retrieve a genuinely relevant doc that
        extractive labels miss, which counts as a miss here.
      </p>
    </div>
  )
}

const SCENARIO_TYPES = ['', 'temporal', 'alias']
const QUERY_TYPES = ['', 'paraphrase', 'temporal', 'adversarial']
const DIFFICULTIES = ['', ...DIFFICULTY_ORDER]

export default function DatasetDetail({ datasetId }: { datasetId: string }) {
  const [detail, setDetail] = useState<ForgeDatasetDetail | null>(null)
  const [queries, setQueries] = useState<ForgeQuery[]>([])
  const [runs, setRuns] = useState<ForgeRunRef[]>([])
  const [error, setError] = useState<string | null>(null)

  const [scenarioFilter, setScenarioFilter] = useState('')
  const [difficultyFilter, setDifficultyFilter] = useState('')
  const [queryTypeFilter, setQueryTypeFilter] = useState('')
  const [validatedOnly, setValidatedOnly] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    setDetail(null)
    setError(null)
    fetchForgeDataset(datasetId).then(setDetail).catch((e) => setError(e.message))
    fetchForgeDatasetRuns(datasetId).then(setRuns).catch(() => setRuns([]))
  }, [datasetId])

  useEffect(() => {
    fetchForgeQueries(datasetId, {
      scenario_type: scenarioFilter || undefined,
      difficulty: difficultyFilter || undefined,
      query_type: queryTypeFilter || undefined,
      validated_only: validatedOnly || undefined,
    })
      .then(setQueries)
      .catch(() => setQueries([]))
  }, [datasetId, scenarioFilter, difficultyFilter, queryTypeFilter, validatedOnly])

  const scenariosByType = useMemo(() => {
    const m: Record<string, ForgeScenario[]> = {}
    for (const s of detail?.scenarios || []) {
      ;(m[s.scenario_type] ||= []).push(s)
    }
    return m
  }, [detail])

  if (error) {
    return <div className="p-6"><div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div></div>
  }
  if (!detail) {
    return (
      <div className="p-6 flex items-center gap-2 text-gray-400 text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 border-t-amber-500" />
        Loading dataset…
      </div>
    )
  }

  const s = detail.summary || {}

  return (
    <div className="p-6 max-w-5xl">
      <div className="mb-6">
        <div className="flex items-center gap-2">
          <span className="text-amber-600 text-lg">🜂</span>
          <h1 className="text-xl font-bold text-gray-900 font-mono">{detail.dataset_id}</h1>
        </div>
        <p className="text-sm text-gray-500 mt-0.5">{detail.corpus_path}</p>
      </div>

      <Section title="Overview" subtitle="What Forge generated and how trustworthy its labels are">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          {[
            ['Scenarios', s.total_scenarios ?? 0],
            ['Queries', s.total_queries ?? 0],
            ['Corpus docs', s.corpus_size ?? 0],
            ['Validated', `${Math.round((detail.validation_coverage || 0) * 100)}%`],
          ].map(([label, val]) => (
            <div key={label as string} className="rounded-lg border border-gray-200 bg-white p-3">
              <p className="text-xs text-gray-500">{label}</p>
              <p className="text-xl font-bold text-gray-900 tabular-nums">{val}</p>
            </div>
          ))}
        </div>
        <div className="mb-4"><LabelTrustBanner coverage={detail.validation_coverage || 0} /></div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <div>
            <p className="text-xs font-semibold text-gray-600 mb-2">By difficulty</p>
            <DistributionBars counts={s.by_difficulty || {}} colorFor={difficultyBarColor} />
          </div>
          <div>
            <p className="text-xs font-semibold text-gray-600 mb-2">By query type</p>
            <DistributionBars counts={s.by_query_type || {}} />
          </div>
        </div>
      </Section>

      <Section
        title="Scenario Explorer"
        subtitle="Structural weaknesses Forge found in your corpus — the patterns that cause retrieval failures"
      >
        {Object.keys(scenariosByType).length === 0 && <p className="text-xs text-gray-400">No scenarios recorded.</p>}
        {Object.entries(scenariosByType).map(([type, list]) => (
          <div key={type} className="mb-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">{type}</span>
              <span className="text-xs text-gray-400">{list.length}</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {list.slice(0, 12).map((sc) => (
                <div key={sc.scenario_id} className="rounded-lg border border-gray-200 bg-white p-3">
                  <p className="text-xs text-gray-700 leading-relaxed">{sc.evidence_summary}</p>
                  <p className="text-[10px] text-gray-400 mt-1.5 font-mono">
                    anchors: {sc.anchor_doc_ids.join(', ')}
                  </p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </Section>

      <Section title="Query Browser" subtitle="The generated hard queries — filter to inspect what each scenario produced">
        <div className="flex flex-wrap items-center gap-2 mb-3 text-xs">
          <FilterSelect label="Scenario" value={scenarioFilter} setValue={setScenarioFilter} options={SCENARIO_TYPES} />
          <FilterSelect label="Difficulty" value={difficultyFilter} setValue={setDifficultyFilter} options={DIFFICULTIES} />
          <FilterSelect label="Type" value={queryTypeFilter} setValue={setQueryTypeFilter} options={QUERY_TYPES} />
          <label className="flex items-center gap-1.5 text-gray-600">
            <input type="checkbox" className="accent-amber-500" checked={validatedOnly} onChange={(e) => setValidatedOnly(e.target.checked)} />
            Validated only
          </label>
          <span className="text-gray-400 ml-auto">{queries.length} shown</span>
        </div>
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 text-gray-500">
              <tr>
                <th className="text-left font-medium px-3 py-2">Query</th>
                <th className="text-left font-medium px-3 py-2 w-24">Type</th>
                <th className="text-left font-medium px-3 py-2 w-24">Difficulty</th>
                <th className="text-center font-medium px-3 py-2 w-20">Pos. docs</th>
                <th className="text-center font-medium px-3 py-2 w-20">Validated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {queries.map((q) => (
                <>
                  <tr
                    key={q.query_id}
                    className="hover:bg-gray-50 cursor-pointer"
                    onClick={() => setExpanded(expanded === q.query_id ? null : q.query_id)}
                  >
                    <td className="px-3 py-2 text-gray-800">{q.text}</td>
                    <td className="px-3 py-2 text-gray-600 capitalize">{q.query_type}</td>
                    <td className="px-3 py-2">
                      <span className={`px-1.5 py-0.5 rounded border text-[10px] font-medium capitalize ${difficultyChipClass(q.difficulty_label)}`}>
                        {q.difficulty_label}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-center tabular-nums text-gray-600">{q.positive_doc_ids.length}</td>
                    <td className="px-3 py-2 text-center">{q.validated ? '✓' : '—'}</td>
                  </tr>
                  {expanded === q.query_id && (
                    <tr key={`${q.query_id}-exp`} className="bg-gray-50">
                      <td colSpan={5} className="px-3 py-2 text-[11px] text-gray-600">
                        <span className="font-medium">Relevant docs:</span> {q.positive_doc_ids.join(', ') || '—'}
                        {q.failure_category && <span className="ml-3"><span className="font-medium">Failure category:</span> {q.failure_category}</span>}
                        <span className="ml-3 font-mono text-gray-400">scenario {q.scenario_id}</span>
                        <a href={`#/query/${encodeURIComponent(q.query_id)}`} className="ml-3 text-indigo-600 hover:underline">View lineage →</a>
                      </td>
                    </tr>
                  )}
                </>
              ))}
              {queries.length === 0 && (
                <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-400">No queries match these filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Stress Test Results" subtitle="Benchmark runs executed against this dataset">
        {runs.length === 0 ? (
          <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-xs text-gray-500">
            No runs have benchmarked this dataset yet. Point a config at this dataset's exported
            <code className="mx-1 px-1 rounded bg-white border border-gray-200">corpus.jsonl</code> /
            <code className="mx-1 px-1 rounded bg-white border border-gray-200">queries.jsonl</code> and run
            <code className="mx-1 px-1 rounded bg-white border border-gray-200">retobs run</code>. The run's per-scenario
            and per-difficulty breakdown will appear in the Benchmarks workspace.
          </div>
        ) : (
          <ul className="space-y-1.5">
            {runs.map((r) => (
              <li key={r.run_id}>
                <a
                  href={`#/benchmarks`}
                  className="flex items-center justify-between rounded-lg border border-gray-200 bg-white p-3 hover:border-indigo-300"
                >
                  <span className="text-sm text-gray-800">{r.experiment_name}</span>
                  <span className="text-xs text-gray-400 font-mono">{r.run_id}</span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  )
}

function FilterSelect({
  label,
  value,
  setValue,
  options,
}: {
  label: string
  value: string
  setValue: (v: string) => void
  options: readonly string[]
}) {
  return (
    <label className="flex items-center gap-1 text-gray-600">
      <span>{label}:</span>
      <select
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="border border-gray-200 rounded px-1.5 py-1 bg-white text-gray-700"
      >
        {options.map((o) => (
          <option key={o} value={o}>{o === '' ? 'all' : o}</option>
        ))}
      </select>
    </label>
  )
}
