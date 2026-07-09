import { Fragment, useEffect, useMemo, useState } from 'react'
import { fetchQueryLabels, QueryLabelRow } from '../api'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'
import { MetricTooltip } from './MetricTooltip'
import CandidateFlowPanel from './CandidateFlowPanel'

const AGREEMENT_STYLE: Record<string, string> = {
  match: 'bg-green-100 text-green-800',
  adjacent: 'bg-amber-100 text-amber-800',
  mismatch: 'bg-red-100 text-red-800',
}

const ALL_CLASSES = ['easy', 'medium', 'hard']

function formatProba(proba: Record<string, number> | null | undefined): string {
  if (!proba) return '—'
  return ALL_CLASSES.map((c) => `${c}:${((proba[c] ?? 0) * 100).toFixed(0)}%`).join(' ')
}

export default function QueryExplorer({ dbId, runId }: { dbId: string; runId: string }) {
  const [items, setItems] = useState<QueryLabelRow[]>([])
  const [filter, setFilter] = useState('')
  const [mismatchOnly, setMismatchOnly] = useState(false)
  const [flowFor, setFlowFor] = useState<string | null>(null)
  const [docId, setDocId] = useState('')

  useEffect(() => {
    fetchQueryLabels(dbId, runId).then((data) => setItems(data.items)).catch(() => setItems([]))
  }, [dbId, runId])

  const filtered = useMemo(() => {
    const needle = filter.toLowerCase()
    return items.filter((item) => {
      if (mismatchOnly && item.agreement !== 'mismatch') return false
      return (
        !needle ||
        item.query_id.toLowerCase().includes(needle) ||
        (item.query_text || '').toLowerCase().includes(needle) ||
        item.actual_bucket.toLowerCase().includes(needle) ||
        (item.actual_class || '').toLowerCase().includes(needle) ||
        (item.predicted_difficulty || '').toLowerCase().includes(needle)
      )
    })
  }, [items, filter, mismatchOnly])
  const visible = filtered.slice(0, 100)

  return (
    <div className="border border-gray-200 dark:border-slate-700 rounded bg-white dark:bg-slate-900">
      <p className="text-xs text-gray-500 dark:text-slate-400 px-3 pt-3 pb-1">
        <strong>Diagnostic buckets (post-hoc from observed recall/variance)</strong>: easy, medium, hard, discriminative, unstable, unknown.
        <strong className="ml-2">Predicted difficulty (pre-retrieval from query text)</strong>: easy, medium, hard, extreme.
        <MetricTooltip text={`${METRIC_GLOSSARY.difficulty_diagnostic}\n\n${METRIC_GLOSSARY.difficulty_predicted}`} />
      </p>
      <p className="text-[11px] text-gray-500 dark:text-slate-400 px-3 pb-2">
        Agreement uses a 3-class fold: easy → easy, medium/discriminative/unstable → medium, hard/extreme → hard.
      </p>
      <div className="p-3 border-b border-gray-100 dark:border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <input
          className="flex-1 min-w-[200px] border border-gray-200 dark:border-slate-700 rounded px-2 py-1 text-sm"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter queries, labels, predicted difficulty"
        />
        <label className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-slate-300">
          <input type="checkbox" checked={mismatchOnly} onChange={(e) => setMismatchOnly(e.target.checked)} className="rounded border-gray-300 dark:border-slate-600" />
          Mismatches only
        </label>
        <span className="text-xs text-gray-400 dark:text-slate-500">{Math.min(visible.length, 100)}/{filtered.length}</span>
      </div>
      <div className="overflow-x-auto max-h-80">
        <table className="min-w-full text-xs">
          <thead className="bg-gray-50 dark:bg-slate-800/60 sticky top-0">
            <tr>
              <th className="text-left px-3 py-2">Query</th>
              <th className="text-left px-3 py-2">Text</th>
              <th className="text-left px-3 py-2">Diagnostic bucket</th>
              <th className="text-left px-3 py-2">Actual (3-class)</th>
              <th className="text-left px-3 py-2">Predicted</th>
              <th className="text-left px-3 py-2">Proba</th>
              <th className="text-left px-3 py-2">Agreement</th>
              <th className="text-left px-3 py-2">Predicted risks</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {visible.map((item) => (
              <Fragment key={item.query_id}>
              <tr className="hover:bg-gray-50">
                <td className="px-3 py-2 font-mono">
                  <a href={`#/query/${encodeURIComponent(item.query_id)}`} className="text-indigo-600 hover:underline">
                    {item.query_id}
                  </a>
                  <button
                    className="ml-2 text-[10px] text-gray-400 hover:text-indigo-600"
                    title="Trace a document's flow through this query's pipelines"
                    onClick={() => {
                      setFlowFor(flowFor === item.query_id ? null : item.query_id)
                      setDocId('')
                    }}
                  >
                    ⇄ flow
                  </button>
                </td>
                <td className="px-3 py-2 max-w-xs truncate" title={item.query_text}>
                  {item.query_text || '—'}
                </td>
                <td className="px-3 py-2 capitalize">{item.actual_bucket}</td>
                <td className="px-3 py-2">{item.actual_class || item.actual_bucket}</td>
                <td className="px-3 py-2">{item.predicted_difficulty || '—'}</td>
                <td className="px-3 py-2 font-mono text-[10px] text-gray-600 dark:text-slate-300">
                  {formatProba(item.predicted_difficulty_proba)}
                </td>
                <td className="px-3 py-2">
                  {item.agreement ? (
                    <span className={`px-1.5 py-0.5 rounded font-medium ${AGREEMENT_STYLE[item.agreement] ?? ''}`}>
                      {item.agreement}
                    </span>
                  ) : '—'}
                </td>
                <td className="px-3 py-2 text-gray-600 dark:text-slate-300">
                  {(item.predicted_risks?.length ?? 0) > 0
                    ? item.predicted_risks!.join(', ')
                    : '—'}
                </td>
              </tr>
              {flowFor === item.query_id && (
                <tr>
                  <td colSpan={8} className="px-3 py-3 bg-gray-50 dark:bg-slate-800/40">
                    <div className="flex items-center gap-2 mb-3">
                      <input
                        className="border border-gray-200 dark:border-slate-700 rounded px-2 py-1 text-xs font-mono"
                        value={docId}
                        onChange={(e) => setDocId(e.target.value)}
                        placeholder="doc_id to trace"
                      />
                    </div>
                    {docId.trim() && (
                      <CandidateFlowPanel dbId={dbId} runId={runId} queryId={item.query_id} docId={docId.trim()} />
                    )}
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {filtered.length > 100 && (
        <div className="px-3 py-2 border-t border-gray-100 dark:border-slate-800 text-xs text-amber-700 bg-amber-50">
          Showing 100 of {filtered.length} queries — refine filters to narrow the list.
        </div>
      )}
    </div>
  )
}
