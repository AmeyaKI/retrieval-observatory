import { useEffect, useState } from 'react'
import {
  fetchAdvisorRecommendations,
  fetchAdvisorRegressions,
  fetchAdvisorReliability,
  fetchDbs,
  fetchRuns,
  Recommendation,
  RegressionFinding,
  ReliabilityScore,
  Run,
} from '../api'

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

type AdvisorView = 'recommendations' | 'regressions'

export default function AdvisorWorkspace() {
  const [dbId, setDbId] = useState<string | null>(null)
  const [view, setView] = useState<AdvisorView>('recommendations')
  const [runs, setRuns] = useState<Run[]>([])
  const [selectedRun, setSelectedRun] = useState('')
  const [baseline, setBaseline] = useState('')
  const [candidate, setCandidate] = useState('')
  const [recommendations, setRecommendations] = useState<Recommendation[]>([])
  const [regressions, setRegressions] = useState<RegressionFinding[]>([])
  const [reliability, setReliability] = useState<ReliabilityScore | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchDbs()
      .then((dbs) => {
        if (dbs.length > 0) setDbId(dbs[0].db_id)
      })
      .catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    if (!dbId) return
    fetchRuns(dbId).then(setRuns).catch((e) => setError(String(e)))
  }, [dbId])

  useEffect(() => {
    if (!selectedRun) return
    setError(null)
    Promise.all([
      fetchAdvisorRecommendations(selectedRun),
      fetchAdvisorReliability(selectedRun),
    ])
      .then(([recRes, relRes]) => {
        setRecommendations(recRes.recommendations)
        setReliability(relRes)
      })
      .catch((e) => setError(String(e)))
  }, [selectedRun])

  const loadRegressions = () => {
    if (!baseline || !candidate) return
    setError(null)
    fetchAdvisorRegressions(baseline, candidate)
      .then((res) => setRegressions(res.regressions))
      .catch((e) => setError(String(e)))
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <header className="shrink-0 border-b border-gray-200 bg-white px-6 py-4">
        <h1 className="text-lg font-semibold text-violet-800">Advisor</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          Rule-based recommendations with cited evidence — heuristics, not guarantees.
        </p>
        {reliability && (
          <div className="mt-3 rounded-lg border border-violet-200 bg-violet-50 p-3 text-xs">
            <p className="font-semibold text-violet-900">
              Reliability score: {(reliability.value * 100).toFixed(0)}%
            </p>
            <div className="flex flex-wrap gap-3 mt-1 text-gray-700">
              {Object.entries(reliability.components).map(([k, v]) => (
                <span key={k}>{k.replace(/_/g, ' ')}: {(v * 100).toFixed(0)}%</span>
              ))}
            </div>
          </div>
        )}
      </header>

      <div className="shrink-0 flex gap-2 px-6 py-2 border-b border-gray-100 bg-white">
        {(['recommendations', 'regressions'] as AdvisorView[]).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setView(v)}
            className={`px-3 py-1.5 rounded text-xs font-medium capitalize ${
              view === v ? 'bg-violet-100 text-violet-800' : 'text-gray-500 hover:bg-gray-50'
            }`}
          >
            {v === 'regressions' ? 'Regression Center' : v}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto p-6">
        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

        {view === 'recommendations' && (
          <>
            <div className="mb-4">
              <label className="text-xs text-gray-500 block mb-1">Run</label>
              <select
                className="text-sm border border-gray-200 rounded px-2 py-1.5"
                value={selectedRun}
                onChange={(e) => setSelectedRun(e.target.value)}
              >
                <option value="">Select a run…</option>
                {runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.experiment_name} ({r.run_id})
                  </option>
                ))}
              </select>
            </div>
            <Section title="Recommendations" subtitle="Ranked by priority">
              {recommendations.length === 0 ? (
                <p className="text-xs text-gray-400">Select a run to see recommendations.</p>
              ) : (
                <div className="space-y-3">
                  {recommendations.map((rec, i) => (
                    <div key={i} className="rounded-lg border border-gray-200 bg-white p-4">
                      <p className="text-sm font-medium text-gray-900">{rec.action}</p>
                      <p className="text-xs text-gray-600 mt-1">{rec.rationale}</p>
                      <ul className="mt-2 text-[11px] text-gray-500 list-disc pl-4">
                        {rec.evidence.map((ev, j) => (
                          <li key={j}>{ev}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </Section>
          </>
        )}

        {view === 'regressions' && (
          <Section title="Regression Center" subtitle="Baseline vs candidate with BH-adjusted q-values">
            <div className="flex flex-wrap gap-3 mb-4">
              <select className="text-sm border rounded px-2 py-1.5" value={baseline} onChange={(e) => setBaseline(e.target.value)}>
                <option value="">Baseline run…</option>
                {runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>{r.run_id}</option>
                ))}
              </select>
              <select className="text-sm border rounded px-2 py-1.5" value={candidate} onChange={(e) => setCandidate(e.target.value)}>
                <option value="">Candidate run…</option>
                {runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>{r.run_id}</option>
                ))}
              </select>
              <button
                type="button"
                onClick={loadRegressions}
                className="px-3 py-1.5 rounded bg-violet-600 text-white text-xs font-medium"
              >
                Compare
              </button>
            </div>
            {regressions.length === 0 ? (
              <p className="text-xs text-gray-400">No significant regressions (or compare not run yet).</p>
            ) : (
              <table className="w-full text-xs border border-gray-200 rounded-lg overflow-hidden">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="text-left px-3 py-2">Metric</th>
                    <th className="text-right px-3 py-2">Before</th>
                    <th className="text-right px-3 py-2">After</th>
                    <th className="text-right px-3 py-2">q-value</th>
                    <th className="text-left px-3 py-2">Severity</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {regressions.map((r) => (
                    <tr key={r.metric}>
                      <td className="px-3 py-2 font-mono text-[10px]">{r.metric}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.before.toFixed(4)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.after.toFixed(4)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.q_value.toFixed(4)}</td>
                      <td className="px-3 py-2 capitalize">{r.severity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
        )}
      </div>
    </div>
  )
}
