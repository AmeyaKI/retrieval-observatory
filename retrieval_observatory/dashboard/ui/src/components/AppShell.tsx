import { useEffect, useState } from 'react'
import ModeRail, { Mode, ShellMode } from './ModeRail'
import BenchmarksWorkspace from './BenchmarksWorkspace'
import ForgeWorkspace from './ForgeWorkspace'
import TraceLensWorkspace from './TraceLensWorkspace'
import AdvisorWorkspace from './AdvisorWorkspace'
import QueryLineagePanel from './QueryLineagePanel'
import GlossaryWorkspace from './GlossaryWorkspace'
import PlatformTour, { PLATFORM_TOUR_STORAGE_KEY } from './PlatformTour'
import DemoQuickLinks from './DemoQuickLinks'
import { DemoContext, fetchDemoContext } from '../api'

const VALID_MODES: Mode[] = ['benchmarks', 'forge', 'tracelens', 'advisor']

function parseHash(): { mode: ShellMode; rest: string } {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const [modePart, ...rest] = raw.split('/')
  if (modePart === 'query') {
    return { mode: 'query', rest: rest.join('/') }
  }
  if (modePart === 'glossary') {
    return { mode: 'glossary', rest: '' }
  }
  const mode = (VALID_MODES as string[]).includes(modePart) ? (modePart as Mode) : 'benchmarks'
  return { mode, rest: rest.join('/') }
}

export default function AppShell() {
  const [{ mode, rest }, setRoute] = useState(parseHash)
  const [demoContext, setDemoContext] = useState<DemoContext | null>(null)
  const [tourOpen, setTourOpen] = useState(false)

  useEffect(() => {
    const onHash = () => setRoute(parseHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    fetchDemoContext()
      .then((ctx) => {
        if (ctx.baseline_run_id) {
          setDemoContext(ctx)
          if (localStorage.getItem(PLATFORM_TOUR_STORAGE_KEY) !== '1') {
            setTourOpen(true)
          }
        }
      })
      .catch(() => setDemoContext(null))
  }, [])

  const selectMode = (next: Mode) => {
    window.location.hash = `#/${next}`
  }

  const showDemoBar = demoContext?.baseline_run_id && mode !== 'glossary'

  return (
    <div className="flex h-screen bg-canvas text-ink font-sans">
      <ModeRail
        mode={mode}
        onSelect={selectMode}
        lineageQueryId={demoContext?.sample_query_id}
        onOpenTour={() => setTourOpen(true)}
        showTourLink={Boolean(demoContext?.baseline_run_id)}
      />
      <div className="flex flex-1 flex-col min-w-0">
        {showDemoBar && demoContext && (
          <DemoQuickLinks context={demoContext} onOpenTour={() => setTourOpen(true)} />
        )}
        {mode === 'query' && rest ? (
          <QueryLineagePanel queryId={rest} />
        ) : mode === 'glossary' ? (
          <GlossaryWorkspace />
        ) : (
          <>
            {mode === 'benchmarks' && <BenchmarksWorkspace demoContext={demoContext} route={rest} />}
            {mode === 'forge' && <ForgeWorkspace route={rest} />}
            {mode === 'tracelens' && <TraceLensWorkspace route={rest} />}
            {mode === 'advisor' && <AdvisorWorkspace />}
          </>
        )}
      </div>
      {demoContext && (
        <PlatformTour context={demoContext} open={tourOpen} onClose={() => setTourOpen(false)} />
      )}
    </div>
  )
}
