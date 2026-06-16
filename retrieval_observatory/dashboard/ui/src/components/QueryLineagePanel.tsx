import { useEffect, useState } from 'react'
import { fetchQueryLineage, QueryLineage } from '../api'

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="mb-6">
      <div className="mb-2">
        <h2 className="text-base font-semibold text-gray-800">{title}</h2>
        {subtitle && <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </section>
  )
}

export default function QueryLineagePanel({ queryId }: { queryId: string }) {
  const [lineage, setLineage] = useState<QueryLineage | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchQueryLineage(queryId)
      .then(setLineage)
      .catch((e) => setError(String(e)))
  }, [queryId])

  if (error) {
    return <div className="p-6 text-sm text-red-600">{error}</div>
  }
  if (!lineage) {
    return <div className="p-6 text-sm text-gray-400">Loading lineage…</div>
  }

  const origin = lineage.origin

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-4xl mx-auto">
        <header className="mb-6">
          <p className="text-xs text-gray-400 uppercase tracking-wide">Query Lineage</p>
          <h1 className="text-lg font-semibold font-mono text-gray-900">{lineage.query_id}</h1>
          {origin.query_text && (
            <p className="text-sm text-gray-600 mt-1">{origin.query_text}</p>
          )}
        </header>

        <Section title="Origin" subtitle={origin.source === 'forge' ? 'Forge-generated stress query' : 'Dataset-native query'}>
          {origin.forge ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs space-y-1">
              <p><span className="font-medium">Dataset:</span> {origin.forge.dataset_id}</p>
              <p><span className="font-medium">Scenario:</span> {origin.forge.scenario_type} ({origin.forge.scenario_id})</p>
              <p><span className="font-medium">Difficulty:</span> {origin.forge.difficulty_label}</p>
              {origin.forge.failure_category && (
                <p><span className="font-medium">Failure category:</span> {origin.forge.failure_category}</p>
              )}
            </div>
          ) : (
            <p className="text-xs text-gray-600">Dataset: {origin.dataset_name || 'unknown'}</p>
          )}
        </Section>

        <Section title="Benchmark evaluations" subtitle="Runs that scored this query">
          {lineage.evaluations.length === 0 ? (
            <p className="text-xs text-gray-400">No benchmark evaluations found.</p>
          ) : (
            <div className="space-y-2">
              {lineage.evaluations.map((ev) => (
                <div key={ev.run_id} className="rounded-lg border border-gray-200 bg-white p-3 text-xs">
                  <p className="font-medium text-gray-800">{ev.experiment_name} <span className="font-mono text-gray-400">({ev.run_id})</span></p>
                  <p className="text-gray-500">{ev.metrics.length} metric rows · {ev.diagnostics.length} diagnostic rows</p>
                </div>
              ))}
            </div>
          )}
        </Section>

        <Section
          title="Production matches (categorical)"
          subtitle={lineage.production_matches.note}
        >
          <p className="text-[11px] text-gray-500 mb-2">
            Match criteria: difficulty={lineage.production_matches.match_difficulty || '—'},{' '}
            labels={lineage.production_matches.match_failure_labels.join(', ') || '—'}
          </p>
          {lineage.production_matches.traces.length === 0 ? (
            <p className="text-xs text-gray-400">No matching production traces.</p>
          ) : (
            <div className="rounded-lg border border-teal-200 overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-teal-50 text-gray-600">
                  <tr>
                    <th className="text-left px-3 py-2">Service</th>
                    <th className="text-left px-3 py-2">Query</th>
                    <th className="text-left px-3 py-2">Difficulty</th>
                    <th className="text-left px-3 py-2">Suspected failures</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {lineage.production_matches.traces.slice(0, 10).map((t) => (
                    <tr key={t.trace_id} className="hover:bg-gray-50">
                      <td className="px-3 py-2">{t.service}</td>
                      <td className="px-3 py-2 max-w-xs truncate" title={t.query_text}>{t.query_text}</td>
                      <td className="px-3 py-2">{t.predicted_difficulty || '—'}</td>
                      <td className="px-3 py-2">{t.suspected_failures?.join(', ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      </div>
    </div>
  )
}
