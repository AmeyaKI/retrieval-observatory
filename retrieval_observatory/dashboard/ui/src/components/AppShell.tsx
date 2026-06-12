import { useEffect, useState } from 'react'
import ModeRail, { Mode } from './ModeRail'
import BenchmarksWorkspace from './BenchmarksWorkspace'
import ForgeWorkspace from './ForgeWorkspace'
import TraceLensWorkspace from './TraceLensWorkspace'

const VALID_MODES: Mode[] = ['benchmarks', 'forge', 'tracelens']

// Hash format: #/<mode>/<rest...>  e.g. #/forge/ds_abc, #/tracelens/prod-search
function parseHash(): { mode: Mode; rest: string } {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const [modePart, ...rest] = raw.split('/')
  const mode = (VALID_MODES as string[]).includes(modePart) ? (modePart as Mode) : 'benchmarks'
  return { mode, rest: rest.join('/') }
}

export default function AppShell() {
  const [{ mode, rest }, setRoute] = useState(parseHash)

  useEffect(() => {
    const onHash = () => setRoute(parseHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const selectMode = (next: Mode) => {
    if (next === mode) return
    window.location.hash = `#/${next}`
  }

  return (
    <div className="flex h-screen bg-gray-50 font-sans">
      <ModeRail mode={mode} onSelect={selectMode} />
      {mode === 'benchmarks' && <BenchmarksWorkspace />}
      {mode === 'forge' && <ForgeWorkspace route={rest} />}
      {mode === 'tracelens' && <TraceLensWorkspace route={rest} />}
    </div>
  )
}
