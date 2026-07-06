import { useTheme } from '../hooks/useTheme'

export type Mode = 'benchmarks' | 'forge' | 'tracelens' | 'advisor'
export type ShellMode = Mode | 'glossary' | 'query'

interface ModeMeta {
  id: Mode
  label: string
  activeText: string
  activeBar: string
  activeBg: string
  icon: (active: boolean) => JSX.Element
}

const STROKE = (active: boolean) => (active ? 2.25 : 1.75)

export const MODES: ModeMeta[] = [
  {
    id: 'benchmarks',
    label: 'Benchmarks',
    activeText: 'text-indigo-600',
    activeBar: 'bg-indigo-600',
    activeBg: 'bg-indigo-50',
    icon: (active) => (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={STROKE(active)} strokeLinecap="round" strokeLinejoin="round">
        <line x1="4" y1="20" x2="4" y2="11" />
        <line x1="10" y1="20" x2="10" y2="4" />
        <line x1="16" y1="20" x2="16" y2="14" />
        <line x1="22" y1="20" x2="2" y2="20" />
      </svg>
    ),
  },
  {
    id: 'forge',
    label: 'Forge',
    activeText: 'text-amber-600',
    activeBar: 'bg-amber-500',
    activeBg: 'bg-amber-50',
    icon: (active) => (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={STROKE(active)} strokeLinecap="round" strokeLinejoin="round">
        <path d="M13 2L4.5 12.5a1 1 0 0 0 .8 1.6H11l-1 7.9 8.5-10.4a1 1 0 0 0-.8-1.6H12l1-7.9z" />
      </svg>
    ),
  },
  {
    id: 'tracelens',
    label: 'TraceLens',
    activeText: 'text-teal-600',
    activeBar: 'bg-teal-500',
    activeBg: 'bg-teal-50',
    icon: (active) => (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={STROKE(active)} strokeLinecap="round" strokeLinejoin="round">
        <path d="M2 12h4l3 8 4-16 3 8h6" />
      </svg>
    ),
  },
  {
    id: 'advisor',
    label: 'Advisor',
    activeText: 'text-violet-600',
    activeBar: 'bg-violet-500',
    activeBg: 'bg-violet-50',
    icon: (active) => (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={STROKE(active)} strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="9" />
        <path d="M9.5 9a2.5 2.5 0 0 1 4.5 1.5c0 1.5-2 2-2 3.5" />
        <line x1="12" y1="17" x2="12" y2="17.5" />
      </svg>
    ),
  },
]

interface Props {
  mode: ShellMode
  onSelect: (mode: Mode) => void
  lineageQueryId?: string | null
  onOpenTour?: () => void
  showTourLink?: boolean
}

function UtilityLink({
  href,
  label,
  active,
  onClick,
}: {
  href?: string
  label: string
  active?: boolean
  onClick?: () => void
}) {
  const className = `w-full text-left px-2 py-1.5 rounded text-[10px] font-medium transition-colors ${
    active ? 'bg-gray-100 dark:bg-slate-800 text-gray-900 dark:text-slate-100' : 'text-gray-500 dark:text-slate-400 hover:text-gray-800 hover:bg-gray-50'
  }`
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={className}>
        {label}
      </button>
    )
  }
  return (
    <a href={href} className={`block ${className}`}>
      {label}
    </a>
  )
}

export default function ModeRail({ mode, onSelect, lineageQueryId, onOpenTour, showTourLink }: Props) {
  const mainMode: Mode = mode === 'glossary' || mode === 'query' ? 'benchmarks' : mode
  const glossaryActive = mode === 'glossary'
  const lineageActive = mode === 'query'
  const lineageHref = lineageQueryId ? `#/query/${encodeURIComponent(lineageQueryId)}` : null
  const { theme, toggle } = useTheme()

  return (
    <nav className="shrink-0 w-20 bg-surface hairline-r flex flex-col items-center py-3 gap-1">
      <div className="mb-3 w-9 h-9 rounded-lg bg-ink text-surface flex items-center justify-center text-[11px] font-bold tracking-tight select-none" title="Retrieval Observatory">
        RO
      </div>
      {MODES.map((m) => {
        const active = m.id === mainMode && !glossaryActive && !lineageActive
        return (
          <button
            key={m.id}
            type="button"
            onClick={() => onSelect(m.id)}
            title={m.label}
            aria-label={m.label}
            aria-current={active ? 'page' : undefined}
            className={`relative w-full flex flex-col items-center gap-1 py-2.5 transition-colors ${
              active ? m.activeText : 'text-gray-400 dark:text-slate-500 hover:text-gray-700'
            }`}
          >
            {active && <span className={`absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-r ${m.activeBar}`} />}
            <span className={`flex items-center justify-center w-9 h-9 rounded-lg ${active ? m.activeBg : ''}`}>
              {m.icon(active)}
            </span>
            <span className="text-[10px] font-medium leading-none whitespace-nowrap px-0.5">{m.label}</span>
          </button>
        )
      })}

      <div className="mt-auto w-full px-1.5 pt-2 hairline-b space-y-0.5" />
      <div className="w-full px-1.5 pt-2 space-y-0.5">
        <UtilityLink href="#/glossary" label="Glossary" active={glossaryActive} />
        {showTourLink && onOpenTour ? (
          <UtilityLink label="Platform tour" onClick={onOpenTour} />
        ) : null}
        {lineageHref ? <UtilityLink href={lineageHref} label="Query lineage" active={lineageActive} /> : null}
        <button
          type="button"
          onClick={toggle}
          className="w-full text-left px-2 py-1.5 rounded text-[10px] font-medium text-ink-faint hover:text-ink hover:bg-surface-muted transition-colors flex items-center gap-1.5"
          title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          aria-label="Toggle theme"
        >
          {theme === 'dark' ? '☀' : '☾'} {theme === 'dark' ? 'Light' : 'Dark'}
        </button>
      </div>
    </nav>
  )
}
