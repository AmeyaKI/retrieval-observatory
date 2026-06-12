import { useEffect, useMemo, useState } from 'react'
import { fetchTraceServices, TraceService } from '../api'
import TraceLensOverview from './tracelens/TraceLensOverview'
import LiveTraces from './tracelens/LiveTraces'
import Distribution from './tracelens/Distribution'
import DriftExplorer from './tracelens/DriftExplorer'
import Hotspots from './tracelens/Hotspots'
import Clusters from './tracelens/Clusters'

interface Props {
  route: string // service name, if any
}

type View = 'overview' | 'traces' | 'distribution' | 'drift' | 'hotspots' | 'clusters'

const VIEWS: { id: View; label: string; desc: string }[] = [
  { id: 'overview', label: 'Overview', desc: 'Headline KPIs for this window' },
  { id: 'traces', label: 'Live Traces', desc: 'Inspect individual requests' },
  { id: 'distribution', label: 'Distribution', desc: 'How traffic is shaped' },
  { id: 'drift', label: 'Drift', desc: 'What changed over time' },
  { id: 'hotspots', label: 'Failure Hotspots', desc: 'Where suspected failures cluster' },
  { id: 'clusters', label: 'Query Clusters', desc: 'Traffic segmentation' },
]

const WINDOWS: { label: string; hours: number | null }[] = [
  { label: 'Last 24h', hours: 24 },
  { label: 'Last 7d', hours: 24 * 7 },
  { label: 'Last 30d', hours: 24 * 30 },
  { label: 'All time', hours: null },
]

export default function TraceLensWorkspace({ route }: Props) {
  const [services, setServices] = useState<TraceService[]>([])
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>('overview')
  const [windowIdx, setWindowIdx] = useState(1) // default Last 7d

  useEffect(() => {
    fetchTraceServices().then(setServices).catch((e) => setError(e.message))
  }, [])

  const activeService = route || services[0]?.service || null

  const since = useMemo(() => {
    const h = WINDOWS[windowIdx].hours
    if (h == null) return undefined
    return new Date(Date.now() - h * 3600 * 1000).toISOString()
  }, [windowIdx])

  const selectService = (svc: string) => {
    window.location.hash = `#/tracelens/${svc}`
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
      </div>
    )
  }

  if (!activeService) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center max-w-md px-6">
          <div className="text-4xl mb-4 select-none">📡</div>
          <p className="text-lg font-semibold text-gray-700">No traces yet</p>
          <p className="text-sm text-gray-500 mt-2 leading-relaxed">
            TraceLens captures production retrieval requests as structured traces so you can inspect any
            request and watch how traffic and retriever behavior drift over time.
          </p>
          <p className="text-sm text-gray-400 mt-3 leading-relaxed">
            Seed sample data with{' '}
            <code className="text-teal-700 bg-teal-50 px-1 rounded">retobs tracelens demo --service demo</code>, or
            push live traces with the <code className="text-teal-700 bg-teal-50 px-1 rounded">TraceRecorder</code> SDK.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-1 min-w-0">
      <aside className="shrink-0 w-60 bg-white border-r border-gray-200 flex flex-col overflow-hidden">
        <div className="px-4 py-4 border-b border-gray-200">
          <h1 className="text-lg font-bold text-gray-900">TraceLens</h1>
          <p className="text-xs text-gray-500 mt-0.5">Production observability</p>
        </div>
        <div className="px-3 py-3 border-b border-gray-100">
          <label className="text-[10px] uppercase tracking-wide text-gray-400">Service</label>
          <select
            value={activeService}
            onChange={(e) => selectService(e.target.value)}
            className="w-full mt-1 border border-gray-200 rounded px-2 py-1.5 text-sm bg-white"
          >
            {services.map((s) => (
              <option key={s.service} value={s.service}>{s.service} ({s.trace_count})</option>
            ))}
          </select>
        </div>
        <nav className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {VIEWS.map((v) => {
            const active = v.id === view
            return (
              <button
                key={v.id}
                type="button"
                onClick={() => setView(v.id)}
                className={`w-full text-left rounded-lg px-3 py-2 transition-colors ${
                  active ? 'bg-teal-50 text-teal-800' : 'text-gray-600 hover:bg-gray-50'
                }`}
              >
                <span className={`block text-sm font-medium ${active ? 'text-teal-800' : 'text-gray-700'}`}>{v.label}</span>
                <span className="block text-[10px] text-gray-400">{v.desc}</span>
              </button>
            )
          })}
        </nav>
      </aside>

      <main className="flex-1 overflow-auto min-w-0">
        {/* Honesty banner — production has no ground truth */}
        <div className="bg-teal-50/70 border-b border-teal-100 px-6 py-2 text-[11px] text-teal-800">
          Production has no ground truth — failures shown here are <strong>suspected</strong> (label-free proxy
          signals), not measured Recall. Measured quality lives in Benchmarks + Forge.
        </div>

        <div className="px-6 py-4">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-base font-semibold text-gray-800">{VIEWS.find((v) => v.id === view)?.label}</h2>
              <p className="text-xs text-gray-400">Service: <span className="font-mono">{activeService}</span></p>
            </div>
            <div className="flex gap-1">
              {WINDOWS.map((w, i) => (
                <button
                  key={w.label}
                  type="button"
                  onClick={() => setWindowIdx(i)}
                  className={`px-2.5 py-1 rounded text-xs border ${
                    i === windowIdx ? 'border-teal-300 bg-teal-50 text-teal-700' : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300'
                  }`}
                >
                  {w.label}
                </button>
              ))}
            </div>
          </div>

          {view === 'overview' && <TraceLensOverview service={activeService} since={since} />}
          {view === 'traces' && <LiveTraces service={activeService} since={since} />}
          {view === 'distribution' && <Distribution service={activeService} since={since} />}
          {view === 'drift' && <DriftExplorer service={activeService} />}
          {view === 'hotspots' && <Hotspots service={activeService} since={since} />}
          {view === 'clusters' && <Clusters service={activeService} since={since} />}
        </div>
      </main>
    </div>
  )
}
