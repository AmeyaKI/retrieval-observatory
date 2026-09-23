import { lazy, Suspense, useEffect, useState } from 'react'
import { useDashboardContext } from '../context/DashboardContext'
import { buildHash, FocusedRoute, landingWorkspace, parseFocusedHash } from '../utils/focusedRoutes'
import GlobalContextBar from './GlobalContextBar'
import type { PipelineHint } from './InvestigateWorkspace'
import MigrationNotice from './MigrationNotice'
import ModeRail, { Mode, ShellMode } from './ModeRail'

const InvestigateWorkspace = lazy(() => import('./InvestigateWorkspace'))
const ConnectWorkspace = lazy(() => import('./ConnectWorkspace'))
const AuditWorkspace = lazy(() => import('./AuditWorkspace'))
const GlossaryWorkspace = lazy(() => import('./GlossaryWorkspace'))

/** Parse the current hash; a lossless legacy link is rewritten in place (no history entry). */
function resolveRoute(): FocusedRoute {
  const route = parseFocusedHash(window.location.hash)
  if (route.redirectTo) {
    window.history.replaceState(null, '', route.redirectTo)
    return parseFocusedHash(route.redirectTo)
  }
  return route
}

function railMode(route: FocusedRoute): ShellMode | null {
  switch (route.workspace) {
    case 'investigate':
    case 'connect':
    case 'audit':
    case 'help':
      return route.workspace
    default:
      return null
  }
}

export default function AppShell() {
  const { selection, databases, databasesLoaded } = useDashboardContext()
  const [route, setRoute] = useState<FocusedRoute>(resolveRoute)
  const [pipelineHint, setPipelineHint] = useState<PipelineHint | null>(null)

  useEffect(() => {
    const onHash = () => {
      const before = window.location.hash
      setRoute(resolveRoute())
      // A redirect rewrote the URL: let the scope provider re-read it.
      if (window.location.hash !== before) window.dispatchEvent(new HashChangeEvent('hashchange'))
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // Landing (`#/` or empty): Investigate when any database has runs, else Connect. Decided
  // only once the database list is known so the wrong workspace never flashes.
  useEffect(() => {
    if (route.workspace !== 'landing' || !databasesLoaded) return
    window.history.replaceState(null, '', buildHash(landingWorkspace(databases), { db: selection.db }))
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  }, [route.workspace, databasesLoaded, databases, selection.db])

  const selectMode = (mode: Mode) => {
    window.location.hash = buildHash(mode, selection)
  }

  const loading = (
    <div className="p-6 text-sm text-ink-muted" role="status">
      Loading workspace…
    </div>
  )

  return (
    <div className="flex h-screen bg-canvas text-ink font-sans">
      <ModeRail mode={railMode(route)} onSelect={selectMode} helpHref={buildHash('help', selection)} />
      <div className="flex flex-1 flex-col min-w-0 pb-16 sm:pb-0">
        <GlobalContextBar workspace={route.workspace} pipelineHint={pipelineHint} />
        <Suspense fallback={loading}>
          {route.workspace === 'landing' && loading}
          {route.workspace === 'investigate' && <InvestigateWorkspace onPipelines={setPipelineHint} />}
          {route.workspace === 'connect' && <ConnectWorkspace />}
          {route.workspace === 'audit' && <AuditWorkspace />}
          {route.workspace === 'help' && <GlossaryWorkspace />}
          {route.workspace === 'migration' && route.retired && (
            <MigrationNotice
              destination={route.retired.destination}
              replacement={route.retired.replacement}
              message={route.retired.message}
              href={buildHash(route.retired.replacement, { db: selection.db })}
            />
          )}
        </Suspense>
      </div>
    </div>
  )
}
