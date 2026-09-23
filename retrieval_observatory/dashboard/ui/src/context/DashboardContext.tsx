import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { DbSource, fetchDbs } from '../api'
import { applySelectionPatch, DashboardSelection, parseDashboardQuery, serializeDashboardQuery } from './dashboardQuery'
export { applySelectionPatch, parseDashboardQuery, serializeDashboardQuery } from './dashboardQuery'
export type { DashboardSelection } from './dashboardQuery'

// The hash query string is the single source of truth for scope. State mirrors it: every
// hashchange re-parses the URL from scratch (plus the database fallback), and
// updateSelection writes the whole selection back before dispatching hashchange.

export interface DashboardContextValue {
  selection: DashboardSelection
  databases: DbSource[]
  /** False until the database list has been fetched (or failed); the landing decision waits on it. */
  databasesLoaded: boolean
  updateSelection: (patch: Partial<DashboardSelection>, mode?: 'push' | 'replace') => void
}

const Context = createContext<DashboardContextValue | null>(null)

function locationQuery(): string {
  const hash = window.location.hash
  const at = hash.indexOf('?')
  return at >= 0 ? hash.slice(at + 1) : ''
}

/** A URL without `db` selects the first known database; a `db` the URL names is kept
 * even when unknown, so a stale link shows a scoped explanation instead of another database's data. */
function withDbFallback(selection: DashboardSelection, databases: DbSource[]): DashboardSelection {
  if (selection.db || databases.length === 0) return selection
  return { ...selection, db: databases[0].db_id }
}

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [selection, setSelection] = useState<DashboardSelection>(() => parseDashboardQuery(locationQuery()))
  const [databases, setDatabases] = useState<DbSource[]>([])
  const [databasesLoaded, setDatabasesLoaded] = useState(false)
  const selectionRef = useRef(selection)
  selectionRef.current = selection
  const databasesRef = useRef(databases)

  useEffect(() => {
    let cancelled = false
    fetchDbs()
      .then((dbs) => {
        if (cancelled) return
        databasesRef.current = dbs
        setDatabases(dbs)
        setSelection((current) => withDbFallback(current, dbs))
      })
      .catch(() => {
        if (!cancelled) setDatabases([])
      })
      .finally(() => {
        if (!cancelled) setDatabasesLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const sync = () => setSelection(withDbFallback(parseDashboardQuery(locationQuery()), databasesRef.current))
    // Re-read after mount: the shell may have rewritten a legacy hash during its first render.
    sync()
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])

  const updateSelection = useCallback((patch: Partial<DashboardSelection>, mode: 'push' | 'replace' = 'push') => {
    const next = withDbFallback(applySelectionPatch(selectionRef.current, patch), databasesRef.current)
    selectionRef.current = next
    setSelection(next)
    const hash = window.location.hash
    const at = hash.indexOf('?')
    const path = (at >= 0 ? hash.slice(0, at) : hash) || '#/'
    const query = serializeDashboardQuery(next)
    window.history[mode === 'replace' ? 'replaceState' : 'pushState'](null, '', query ? `${path}?${query}` : path)
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  }, [])

  const value = useMemo(
    () => ({ selection, databases, databasesLoaded, updateSelection }),
    [selection, databases, databasesLoaded, updateSelection],
  )
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useDashboardContext(): DashboardContextValue {
  const value = useContext(Context)
  if (!value) throw new Error('DashboardProvider required')
  return value
}
