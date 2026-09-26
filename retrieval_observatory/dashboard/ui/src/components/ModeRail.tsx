import { useTheme } from '../hooks/useTheme'

export type Mode = 'investigate' | 'connect' | 'audit'
export type ShellMode = Mode | 'help'

/** Exactly three feature destinations (master plan 2.2); Help and theme are utilities. */
export const PRIMARY_MODES: Array<{ id: Mode; label: string; icon: string }> = [
  { id: 'investigate', label: 'Investigate', icon: '⌕' },
  { id: 'connect', label: 'Connect', icon: '⊸' },
  { id: 'audit', label: 'Audit', icon: '⚖' },
]

interface Props {
  mode: ShellMode | null
  onSelect: (mode: Mode) => void
  /** Help link target; the shell passes one that carries the current scope. */
  helpHref?: string
}

export default function ModeRail({ mode, onSelect, helpHref = '#/help' }: Props) {
  const { theme, toggle } = useTheme()
  const utilityClass =
    'rounded px-2 py-1.5 text-[10px] text-ink-muted hover:bg-surface-muted hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 whitespace-nowrap'

  return (
    <nav
      aria-label="Primary"
      className="fixed sm:static bottom-0 inset-x-0 z-40 h-16 sm:h-auto sm:w-24 bg-surface border-t sm:border-t-0 sm:hairline-r border-slate-200 dark:border-slate-700 flex sm:flex-col items-stretch sm:items-center px-1 sm:px-0 sm:py-3 gap-0 sm:gap-1"
    >
      <p className="hidden sm:flex mb-3 w-9 h-9 rounded-lg bg-ink text-surface items-center justify-center text-[11px] font-bold select-none">
        <abbr title="Retrieval Observatory" className="no-underline">
          RO
        </abbr>
      </p>
      {PRIMARY_MODES.map((item) => {
        const active = item.id === mode
        return (
          <button
            key={item.id}
            type="button"
            data-mode={item.id}
            onClick={() => onSelect(item.id)}
            aria-current={active ? 'page' : undefined}
            className={`relative flex-1 sm:flex-none sm:w-full h-full sm:h-auto flex flex-col items-center justify-center gap-1 sm:py-2 rounded-md transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 ${
              active ? 'bg-surface-muted text-ink font-semibold' : 'text-ink-muted hover:text-ink hover:bg-surface-muted'
            }`}
          >
            {active && (
              <span className="absolute left-2 right-2 top-0 h-0.5 sm:left-0 sm:right-auto sm:top-2 sm:bottom-2 sm:h-auto sm:w-0.5 rounded bg-indigo-600" />
            )}
            <span aria-hidden="true" className="text-lg leading-none">
              {item.icon}
            </span>
            <span className="text-[10px] leading-none whitespace-nowrap">{item.label}</span>
          </button>
        )
      })}
      <div className="flex sm:flex-col items-center sm:items-stretch sm:mt-auto sm:w-full sm:px-2 sm:space-y-1 pl-1 sm:pl-2">
        <a
          href={helpHref}
          data-utility="help"
          aria-current={mode === 'help' ? 'page' : undefined}
          className={`${utilityClass} ${mode === 'help' ? 'bg-surface-muted text-ink font-semibold' : ''}`}
        >
          Help
        </a>
        <button type="button" onClick={toggle} className={`${utilityClass} text-left`} aria-label="Toggle theme">
          {theme === 'dark' ? 'Light theme' : 'Dark theme'}
        </button>
      </div>
    </nav>
  )
}
