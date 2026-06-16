import { useEffect, useState } from 'react'
import ModeRail, { Mode } from './ModeRail'
import BenchmarksWorkspace from './BenchmarksWorkspace'
import ForgeWorkspace from './ForgeWorkspace'
import TraceLensWorkspace from './TraceLensWorkspace'
import AdvisorWorkspace from './AdvisorWorkspace'
import QueryLineagePanel from './QueryLineagePanel'

const VALID_MODES: Mode[] = ['benchmarks', 'forge', 'tracelens', 'advisor']

function parseHash(): { mode: Mode | 'query'; rest: string } {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const [modePart, ...rest] = raw.split('/')
  if (modePart === 'query') {
    return { mode: 'query', rest: rest.join('/') }
  }
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

  if (mode === 'query' && rest) {
    return (
      <div className="flex h-screen bg-gray-50 font-sans">
        <ModeRail mode="benchmarks" onSelect={selectMode} />
        <QueryLineagePanel queryId={rest} />
      </div>
    )
  }

  return (
    <div className="flex h-screen bg-gray-50 font-sans">
      <ModeRail mode={mode as Mode} onSelect={selectMode} />
      {mode === 'benchmarks' && <BenchmarksWorkspace />}
      {mode === 'forge' && <ForgeWorkspace route={rest} />}
      {mode === 'tracelens' && <TraceLensWorkspace route={rest} />}
      {mode === 'advisor' && <AdvisorWorkspace />}
    </div>
  )
}
