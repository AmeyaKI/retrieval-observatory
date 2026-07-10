import { useEffect, useState } from 'react'
import {
  fetchConfigDiff,
  fetchOperatorAttribution,
  fetchAdvisorRecommendations,
  fetchPipelineGraphs,
  ConfigDiffResult,
  OperatorAttributionRow,
  PipelineGraph,
  QueryDiffs,
  Recommendation,
  RunSelection,
} from '../api'
import NoData from './NoData'
import SectionHeading from './SectionHeading'

// Item D: deeper Run Comparison diffs. Only meaningful for exactly two runs -- everything
// here is a pairwise structural or statistical diff, not an N-way aggregate.
export default function RunComparisonDeepDiffs({
  selections,
  queryDiffs,
}: {
  selections: RunSelection[]
  queryDiffs: QueryDiffs | null | undefined
}) {
  if (selections.length !== 2) return null
  const [runA, runB] = selections

  return (
    <div className="mt-8 space-y-8">
      <QueryDiffsSection queryDiffs={queryDiffs} runA={runA} />
      <TopologyDiffSection runA={runA} runB={runB} />
      <AttributionDiffSection runA={runA} runB={runB} />
      <RecommendationDiffSection runA={runA} runB={runB} />
      <ConfigDiffSection runA={runA} runB={runB} />
    </div>
  )
}

function QueryDiffsSection({ queryDiffs, runA }: { queryDiffs: QueryDiffs | null | undefined; runA: RunSelection }) {
  return (
    <div>
      <SectionHeading title="Query-level winners & losers" />
      {!queryDiffs ? (
        <NoData label="No paired per-query quality metric available for these two runs (different datasets, or no shared queries)." />
      ) : (
        <div>
          <p className="text-xs text-ink-muted mb-2">
            {queryDiffs.metric} — Run A minus Run B, sorted by magnitude of change.
          </p>
          <table className="w-full text-xs border border-gray-200 dark:border-slate-700 rounded overflow-hidden">
            <thead className="bg-gray-50 dark:bg-slate-800/60">
              <tr className="text-left">
                <th className="px-3 py-1.5">Query</th>
                <th className="px-3 py-1.5 text-right">A</th>
                <th className="px-3 py-1.5 text-right">B</th>
                <th className="px-3 py-1.5 text-right">Delta</th>
                <th className="px-3 py-1.5"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-slate-800">
              {queryDiffs.rows.slice(0, 25).map((row) => (
                <tr key={row.query_id}>
                  <td className="px-3 py-1.5 font-mono">{row.query_id}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{row.a.toFixed(3)}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{row.b.toFixed(3)}</td>
                  <td className={`px-3 py-1.5 text-right font-mono font-semibold ${row.delta > 0 ? 'text-emerald-700' : row.delta < 0 ? 'text-red-600' : 'text-ink-faint'}`}>
                    {row.delta > 0 ? '+' : ''}{row.delta.toFixed(3)}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <a
                      href={`#/benchmarks/run/${encodeURIComponent(runA.runId)}/queries/${encodeURIComponent(row.query_id)}/diff?against=${encodeURIComponent(queryDiffs.run_b)}`}
                      className="text-indigo-600 hover:underline"
                    >
                      diff →
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function TopologyDiffSection({ runA, runB }: { runA: RunSelection; runB: RunSelection }) {
  const [graphsA, setGraphsA] = useState<PipelineGraph[] | null>(null)
  const [graphsB, setGraphsB] = useState<PipelineGraph[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setGraphsA(null)
    setGraphsB(null)
    setError(null)
    Promise.all([fetchPipelineGraphs(runA.dbId, runA.runId), fetchPipelineGraphs(runB.dbId, runB.runId)])
      .then(([a, b]) => {
        setGraphsA(a)
        setGraphsB(b)
      })
      .catch((e) => setError(e.message))
  }, [runA.dbId, runA.runId, runB.dbId, runB.runId])

  if (error) return <NoData label={error} />
  if (!graphsA || !graphsB) return <div className="text-xs text-ink-faint">Loading topology diff…</div>

  const byPipelineA = new Map(graphsA.map((g) => [g.pipeline_id, g]))
  const byPipelineB = new Map(graphsB.map((g) => [g.pipeline_id, g]))
  const commonPipelines = Array.from(byPipelineA.keys()).filter((p) => byPipelineB.has(p))

  return (
    <div>
      <SectionHeading title="Topology diff" />
      {commonPipelines.length === 0 ? (
        <NoData label="No pipeline_id present in both runs' topology." />
      ) : (
        <div className="space-y-3">
          {commonPipelines.map((pipelineId) => {
            const a = byPipelineA.get(pipelineId)!
            const b = byPipelineB.get(pipelineId)!
            const nodesA = new Set(a.nodes.map((n) => n.node_id))
            const nodesB = new Set(b.nodes.map((n) => n.node_id))
            const addedNodes = a.nodes.filter((n) => !nodesB.has(n.node_id))
            const removedNodes = b.nodes.filter((n) => !nodesA.has(n.node_id))
            const edgeKey = (e: { source: string; target: string }) => `${e.source}->${e.target}`
            const edgesA = new Set(a.edges.map(edgeKey))
            const edgesB = new Set(b.edges.map(edgeKey))
            const addedEdges = a.edges.filter((e) => !edgesB.has(edgeKey(e)))
            const removedEdges = b.edges.filter((e) => !edgesA.has(edgeKey(e)))
            const unchanged = addedNodes.length === 0 && removedNodes.length === 0 && addedEdges.length === 0 && removedEdges.length === 0
            return (
              <div key={pipelineId} className="border border-gray-200 dark:border-slate-700 rounded-lg p-3">
                <div className="font-mono text-sm font-semibold mb-2">{pipelineId}</div>
                {unchanged ? (
                  <div className="text-xs text-ink-faint">No topology differences.</div>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {addedNodes.map((n) => (
                      <span key={`add-${n.node_id}`} className="text-[11px] px-1.5 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300">
                        + {n.label} ({n.op_type})
                      </span>
                    ))}
                    {removedNodes.map((n) => (
                      <span key={`rm-${n.node_id}`} className="text-[11px] px-1.5 py-0.5 rounded bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300 line-through">
                        {n.label} ({n.op_type})
                      </span>
                    ))}
                    {addedEdges.map((e) => (
                      <span key={`ae-${edgeKey(e)}`} className="text-[11px] px-1.5 py-0.5 rounded bg-emerald-50/60 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400 font-mono">
                        + {e.source}→{e.target}
                      </span>
                    ))}
                    {removedEdges.map((e) => (
                      <span key={`re-${edgeKey(e)}`} className="text-[11px] px-1.5 py-0.5 rounded bg-red-50/60 dark:bg-red-950/20 text-red-600 dark:text-red-400 font-mono line-through">
                        {e.source}→{e.target}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function bestRowsByOp(rows: OperatorAttributionRow[]): Map<string, OperatorAttributionRow> {
  const m = new Map<string, OperatorAttributionRow>()
  for (const row of rows) {
    const existing = m.get(row.op_id)
    if (!existing || row.n_pairs > existing.n_pairs) m.set(row.op_id, row)
  }
  return m
}

function AttributionDiffSection({ runA, runB }: { runA: RunSelection; runB: RunSelection }) {
  const [rowsA, setRowsA] = useState<OperatorAttributionRow[] | null>(null)
  const [rowsB, setRowsB] = useState<OperatorAttributionRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setRowsA(null)
    setRowsB(null)
    setError(null)
    Promise.all([fetchOperatorAttribution(runA.dbId, runA.runId), fetchOperatorAttribution(runB.dbId, runB.runId)])
      .then(([a, b]) => {
        setRowsA(a)
        setRowsB(b)
      })
      .catch((e) => setError(e.message))
  }, [runA.dbId, runA.runId, runB.dbId, runB.runId])

  if (error) return <NoData label={error} />
  if (!rowsA || !rowsB) return <div className="text-xs text-ink-faint">Loading attribution diff…</div>

  const byOpA = bestRowsByOp(rowsA)
  const byOpB = bestRowsByOp(rowsB)
  const commonOps = Array.from(byOpA.keys()).filter((id) => byOpB.has(id))
  const flips = commonOps
    .map((opId) => ({ opId, a: byOpA.get(opId)!, b: byOpB.get(opId)! }))
    .filter(({ a, b }) => {
      const signFlip = a.delta != null && b.delta != null && Math.sign(a.delta) !== Math.sign(b.delta) && a.delta !== 0 && b.delta !== 0
      const sigChange = Boolean(a.significant) !== Boolean(b.significant)
      return signFlip || sigChange
    })

  return (
    <div>
      <SectionHeading title="Attribution diff" />
      {commonOps.length === 0 ? (
        <NoData label="No operator present in both runs' attribution results." />
      ) : flips.length === 0 ? (
        <div className="text-xs text-ink-faint">No operator's contribution direction or significance changed.</div>
      ) : (
        <table className="w-full text-xs border border-gray-200 dark:border-slate-700 rounded overflow-hidden">
          <thead className="bg-gray-50 dark:bg-slate-800/60">
            <tr className="text-left">
              <th className="px-3 py-1.5">Operator</th>
              <th className="px-3 py-1.5 text-right">Delta (A)</th>
              <th className="px-3 py-1.5 text-right">Delta (B)</th>
              <th className="px-3 py-1.5">Change</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-slate-800">
            {flips.map(({ opId, a, b }) => (
              <tr key={opId}>
                <td className="px-3 py-1.5 font-mono">{opId}</td>
                <td className="px-3 py-1.5 text-right font-mono">{a.delta?.toFixed(4) ?? '—'}</td>
                <td className="px-3 py-1.5 text-right font-mono">{b.delta?.toFixed(4) ?? '—'}</td>
                <td className="px-3 py-1.5 text-amber-700">
                  {Math.sign(a.delta ?? 0) !== Math.sign(b.delta ?? 0) ? 'direction flipped' : 'significance changed'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function RecommendationDiffSection({ runA, runB }: { runA: RunSelection; runB: RunSelection }) {
  const [recsA, setRecsA] = useState<Recommendation[] | null>(null)
  const [recsB, setRecsB] = useState<Recommendation[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setRecsA(null)
    setRecsB(null)
    setError(null)
    Promise.all([fetchAdvisorRecommendations(runA.runId), fetchAdvisorRecommendations(runB.runId)])
      .then(([a, b]) => {
        setRecsA(a.recommendations)
        setRecsB(b.recommendations)
      })
      .catch((e) => setError(e.message))
  }, [runA.runId, runB.runId])

  if (error) return <NoData label={error} />
  if (!recsA || !recsB) return <div className="text-xs text-ink-faint">Loading recommendation diff…</div>

  const actionsA = new Set(recsA.map((r) => r.action))
  const actionsB = new Set(recsB.map((r) => r.action))
  const newRecs = recsA.filter((r) => !actionsB.has(r.action))
  const resolvedRecs = recsB.filter((r) => !actionsA.has(r.action))
  const persisting = recsA.filter((r) => actionsB.has(r.action))

  return (
    <div>
      <SectionHeading title="Recommendation diff" />
      {newRecs.length === 0 && resolvedRecs.length === 0 && persisting.length === 0 ? (
        <NoData label="Neither run has any Advisor recommendations." />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
          <RecList title="New (A only)" items={newRecs} className="text-amber-700" />
          <RecList title="Resolved (B only)" items={resolvedRecs} className="text-emerald-700" />
          <RecList title="Persisting" items={persisting} className="text-ink-muted" />
        </div>
      )}
    </div>
  )
}

function RecList({ title, items, className }: { title: string; items: Recommendation[]; className: string }) {
  return (
    <div className="border border-gray-100 dark:border-slate-800 rounded p-2">
      <div className={`font-semibold mb-1 ${className}`}>{title} ({items.length})</div>
      {items.length === 0 ? (
        <div className="text-ink-faint">—</div>
      ) : (
        <ul className="space-y-1">
          {items.slice(0, 6).map((r, i) => (
            <li key={i} className="truncate" title={r.action}>{r.action}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ConfigDiffSection({ runA, runB }: { runA: RunSelection; runB: RunSelection }) {
  const [diff, setDiff] = useState<ConfigDiffResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setDiff(null)
    setError(null)
    fetchConfigDiff([runA, runB])
      .then(setDiff)
      .catch((e) => setError(e.message))
  }, [runA.dbId, runA.runId, runB.dbId, runB.runId])

  if (error) return <NoData label={error} />
  if (!diff) return <div className="text-xs text-ink-faint">Loading config diff…</div>

  const changedPipelines = diff.pipeline_diffs.filter((p) => p.change !== 'unchanged')

  return (
    <div>
      <SectionHeading title="Config diff" />
      {!diff.has_changes ? (
        <div className="text-xs text-ink-faint">No structural configuration differences between these runs.</div>
      ) : (
        <div className="space-y-2">
          {diff.dataset_changed && (
            <div className="text-xs text-amber-700 bg-amber-50 dark:bg-amber-950/30 rounded px-2 py-1">Dataset configuration changed.</div>
          )}
          {diff.metrics_changed && (
            <div className="text-xs text-amber-700 bg-amber-50 dark:bg-amber-950/30 rounded px-2 py-1">Metrics configuration changed.</div>
          )}
          {changedPipelines.map((p) => (
            <div key={p.pipeline_id} className="border border-gray-100 dark:border-slate-800 rounded p-2 text-xs">
              <div className="font-mono font-semibold mb-1">
                {p.pipeline_id} <span className="text-ink-faint font-sans">({p.change})</span>
              </div>
              {p.stage_diffs.filter((s) => s.change !== 'unchanged').map((s) => (
                <div key={s.index} className="pl-2 text-ink-muted">
                  stage {s.index}: {s.change}
                  {s.change === 'changed' && (
                    <span className="ml-1 font-mono text-[10px]">
                      {JSON.stringify(s.before)} → {JSON.stringify(s.after)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
