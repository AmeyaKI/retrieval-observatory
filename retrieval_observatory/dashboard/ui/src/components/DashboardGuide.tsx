import { useState } from 'react'

const STORAGE_KEY = 'retobs_dashboard_guide_dismissed'

export default function DashboardGuide() {
  const [open, setOpen] = useState(() => localStorage.getItem(STORAGE_KEY) !== '1')
  const [collapsed, setCollapsed] = useState(false)

  if (!open) return null

  const dismiss = () => {
    localStorage.setItem(STORAGE_KEY, '1')
    setOpen(false)
  }

  return (
    <div className="mb-6 border border-indigo-200 rounded-lg bg-indigo-50/60 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-indigo-100">
        <span className="text-sm font-semibold text-indigo-900">How to read this dashboard</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            className="text-xs text-indigo-600 hover:text-indigo-800"
          >
            {collapsed ? 'Expand' : 'Collapse'}
          </button>
          <button type="button" onClick={dismiss} className="text-xs text-gray-500 hover:text-gray-700">
            Dismiss
          </button>
        </div>
      </div>
      {!collapsed && (
        <div className="px-4 py-3 text-xs text-indigo-900 space-y-2">
          <ol className="list-decimal list-inside space-y-1">
            <li><strong>Experiment Overview</strong> — headline winner, query difficulty, failure labels, classifier calibration.</li>
            <li><strong>Pipeline Verdict</strong> — all pipelines ranked by final-stage NDCG@10. Stage Ablation Attribution only applies to prefix pairs (e.g. bm25 → bm25__rerank).</li>
            <li><strong>Charts</strong> — compare quality/latency tradeoffs. Use Fit/+/- or ⌘/Ctrl+scroll over a chart to zoom.</li>
            <li><strong>Query Explorer</strong> — per-query actual vs predicted difficulty and agreement.</li>
          </ol>
          <p className="text-indigo-700">
            Multi-architecture runs (bm25, dense_only, rrf_hybrid, …) compare independent pipelines.
            Ablation runs (bm25 → bm25__rerank → …) add stage-by-stage attribution cards.
          </p>
        </div>
      )}
    </div>
  )
}
