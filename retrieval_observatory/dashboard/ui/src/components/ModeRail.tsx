import { useTheme } from '../hooks/useTheme'

export type Mode = 'home' | 'runs' | 'compare' | 'queries' | 'production' | 'test-sets'
export type ShellMode = Mode | 'glossary'

const MODES: Array<{ id: Mode; label: string; icon: string }> = [
  { id: 'home', label: 'Home', icon: '⌂' },
  { id: 'runs', label: 'Runs', icon: '▥' },
  { id: 'compare', label: 'Compare', icon: '⇄' },
  { id: 'queries', label: 'Queries', icon: '?' },
  { id: 'production', label: 'Production', icon: '⌁' },
  { id: 'test-sets', label: 'Test Sets', icon: '◇' },
]

interface Props {
  mode: ShellMode
  onSelect: (mode: Mode) => void
  onOpenTour?: () => void
  showTourLink?: boolean
}

export default function ModeRail({ mode, onSelect, onOpenTour, showTourLink }: Props) {
  const { theme, toggle } = useTheme()
  return (
    <nav aria-label="Primary" className="fixed sm:static bottom-0 inset-x-0 z-40 h-16 sm:h-auto sm:w-24 bg-surface border-t sm:border-t-0 sm:hairline-r border-slate-200 dark:border-slate-700 flex sm:flex-col items-center px-1 sm:px-0 sm:py-3 gap-0 sm:gap-1">
      <a href="#/home" className="hidden sm:flex mb-3 w-9 h-9 rounded-lg bg-ink text-surface items-center justify-center text-[11px] font-bold" title="Retrieval Observatory">RO</a>
      {MODES.map((item) => {
        const active = item.id === mode
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelect(item.id)}
            aria-current={active ? 'page' : undefined}
            className={`relative flex-1 sm:flex-none sm:w-full h-full sm:h-auto flex flex-col items-center justify-center gap-1 sm:py-2 rounded-md transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 ${active ? 'bg-surface-muted text-ink font-semibold' : 'text-ink-muted hover:text-ink hover:bg-surface-muted'}`}
          >
            {active && <span className="absolute left-2 right-2 top-0 h-0.5 sm:left-0 sm:right-auto sm:top-2 sm:bottom-2 sm:h-auto sm:w-0.5 rounded bg-indigo-600" />}
            <span aria-hidden="true" className="text-lg leading-none">{item.icon}</span>
            <span className="text-[10px] leading-none whitespace-nowrap">{item.label}</span>
          </button>
        )
      })}
      <div className="hidden sm:block mt-auto w-full px-2 space-y-1 text-[10px]">
        <a href="#/glossary" aria-current={mode === 'glossary' ? 'page' : undefined} className="block rounded px-2 py-1.5 text-ink-muted hover:bg-surface-muted hover:text-ink">Glossary</a>
        {showTourLink && onOpenTour && <button type="button" onClick={onOpenTour} className="w-full rounded px-2 py-1.5 text-left text-ink-muted hover:bg-surface-muted hover:text-ink">Tour</button>}
        <button type="button" onClick={toggle} className="w-full rounded px-2 py-1.5 text-left text-ink-muted hover:bg-surface-muted hover:text-ink" aria-label="Toggle theme">
          {theme === 'dark' ? 'Light theme' : 'Dark theme'}
        </button>
      </div>
    </nav>
  )
}
