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
        <span className="text-sm font-semibold text-indigo-900">How to use this dashboard</span>
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
        <div className="px-4 py-3 text-xs text-indigo-900 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <p className="font-semibold mb-1">Reading the results</p>
              <ol className="list-decimal list-inside space-y-1 text-indigo-800">
                <li><strong>Experiment Overview</strong> — headline winner, query difficulty, failure labels</li>
                <li><strong>Pipeline Verdict</strong> — all pipelines ranked by NDCG@10, with stage attribution for prefix pairs</li>
                <li><strong>Metrics Summary</strong> — full table of Recall, NDCG, MRR, latency across all pipelines</li>
                <li><strong>Query Explorer</strong> — drill into individual queries to see why they failed</li>
              </ol>
            </div>
            <div>
              <p className="font-semibold mb-1">Navigating charts</p>
              <ul className="list-disc list-inside space-y-1 text-indigo-800">
                <li>Click <strong>Expand ⤢</strong> to open a chart full-screen</li>
                <li>Use <strong>+ / −</strong> buttons or pinch on trackpad to zoom Y-axis</li>
                <li>Click <strong>Fit</strong> to snap Y-axis to your data range</li>
                <li>Click <strong>Reset</strong> to return to default 0–1 scale</li>
                <li>Click legend items to hide/show individual series</li>
              </ul>
            </div>
          </div>
          <div className="border-t border-indigo-100 pt-2">
            <p className="font-semibold mb-1">Two types of runs</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div className="bg-white/60 rounded p-2 border border-indigo-100">
                <p className="font-medium text-indigo-800">Multi-architecture runs</p>
                <p className="text-indigo-700 mt-0.5">Compare independent pipelines: bm25, dense_only, rrf_hybrid. Stage Attribution is not available — these are not prefix pairs of each other.</p>
              </div>
              <div className="bg-white/60 rounded p-2 border border-indigo-100">
                <p className="font-medium text-indigo-800">Ablation runs</p>
                <p className="text-indigo-700 mt-0.5">Compare prefix pipeline pairs: bm25 → bm25__rerank. Stage Attribution cards show exactly what the reranker added in quality and latency cost.</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
