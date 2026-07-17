import { lazy, Suspense, useEffect, useState } from 'react'
import { DemoContext, fetchDemoContext } from '../api'
import { useDashboardContext } from '../context/DashboardContext'
import GlobalContextBar from './GlobalContextBar'
import DemoQuickLinks from './DemoQuickLinks'
import HomeWorkspace from './HomeWorkspace'
import ModeRail, { Mode, ShellMode } from './ModeRail'
import PlatformTour from './PlatformTour'

const BenchmarksWorkspace = lazy(() => import('./BenchmarksWorkspace'))
const ForgeWorkspace = lazy(() => import('./ForgeWorkspace'))
const GlossaryWorkspace = lazy(() => import('./GlossaryWorkspace'))
const QueryLineagePanel = lazy(() => import('./QueryLineagePanel'))
const TraceLensWorkspace = lazy(() => import('./TraceLensWorkspace'))

const VALID_MODES: Mode[] = ['home', 'runs', 'compare', 'queries', 'production', 'test-sets']

function parseHash(): { mode: ShellMode; rest: string } {
  let raw = window.location.hash.replace(/^#\/?/, '')
  if (raw.startsWith('benchmarks/run/')) {
    raw = raw.replace(/^benchmarks\/run\//, 'runs/')
    window.history.replaceState(null, '', `#/${raw}`)
  }
  const [path] = raw.split('?'); const [modePart, ...rest] = path.split('/')
  if (modePart === 'glossary') return { mode: 'glossary', rest: '' }
  const mode = (VALID_MODES as string[]).includes(modePart) ? (modePart as Mode) : 'home'
  return { mode, rest: rest.join('/') }
}

export default function AppShell() {
  const [{ mode, rest }, setRoute] = useState(parseHash)
  const [demoContext, setDemoContext] = useState<DemoContext | null>(null)
  const [tourOpen, setTourOpen] = useState(false)
  const { selection } = useDashboardContext(); const dbId = selection.db

  useEffect(() => {
    const onHash = () => setRoute(parseHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    fetchDemoContext().then(setDemoContext).catch(() => setDemoContext(null))
  }, [])

  const selectMode = (next: Mode) => { window.location.hash = `#/${next}` }
  const showDemoBar = Boolean(demoContext?.baseline_run_id) && mode !== 'glossary'

  return (
    <div className="flex h-screen bg-canvas text-ink font-sans">
      <ModeRail mode={mode} onSelect={selectMode} onOpenTour={() => setTourOpen(true)} showTourLink={Boolean(demoContext?.baseline_run_id)} />
      <div className="flex flex-1 flex-col min-w-0 pb-16 sm:pb-0">
        {showDemoBar && demoContext && <DemoQuickLinks context={demoContext} onOpenTour={() => setTourOpen(true)} />}
        <GlobalContextBar />
        <Suspense fallback={<div className="p-6 text-sm text-ink-muted" role="status">Loading workspace…</div>}>
          {mode === 'home' && <HomeWorkspace context={demoContext} />}
          {mode === 'runs' && <BenchmarksWorkspace demoContext={demoContext} route={rest} view="runs" />}
          {mode === 'compare' && <BenchmarksWorkspace demoContext={demoContext} view="compare" />}
          {mode === 'queries' && rest && dbId && <QueryLineagePanel dbId={dbId} queryId={rest} />}
          {mode === 'queries' && !rest && <BenchmarksWorkspace demoContext={demoContext} view="queries" />}
          {mode === 'production' && dbId && <TraceLensWorkspace dbId={dbId} route={rest} />}
          {mode === 'test-sets' && dbId && <ForgeWorkspace dbId={dbId} route={rest} />}
          {mode === 'glossary' && <GlossaryWorkspace />}
        </Suspense>
      </div>
      {demoContext && <PlatformTour context={demoContext} open={tourOpen} onClose={() => setTourOpen(false)} />}
    </div>
  )
}
