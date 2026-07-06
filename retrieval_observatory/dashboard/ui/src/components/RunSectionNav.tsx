import { useEffect, useState } from 'react'

export interface RunSection {
  id: string
  label: string
}

interface Props {
  sections: RunSection[]
  activeId?: string
}

export default function RunSectionNav({ sections, activeId }: Props) {
  const [current, setCurrent] = useState(activeId ?? sections[0]?.id ?? '')

  useEffect(() => {
    if (activeId) setCurrent(activeId)
  }, [activeId])

  useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)
        if (visible[0]?.target.id) setCurrent(visible[0].target.id)
      },
      { rootMargin: '-20% 0px -65% 0px', threshold: [0, 0.25, 0.5] },
    )
    for (const s of sections) {
      const el = document.getElementById(s.id)
      if (el) obs.observe(el)
    }
    return () => obs.disconnect()
  }, [sections])

  return (
    <nav
      className="sticky top-12 z-20 -mx-6 px-6 py-2 mb-4 bg-canvas/95 backdrop-blur border-b border-gray-200 dark:border-slate-700 overflow-x-auto"
      aria-label="Run sections"
    >
      <div className="flex gap-1 min-w-max">
        {sections.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            onClick={(e) => {
              e.preventDefault()
              document.getElementById(s.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
              setCurrent(s.id)
              window.history.replaceState(null, '', `#${s.id}`)
            }}
            className={`text-xs px-2.5 py-1 rounded-md whitespace-nowrap transition-colors ${
              current === s.id
                ? 'bg-indigo-100 dark:bg-indigo-950 text-indigo-800 dark:text-indigo-200 font-semibold'
                : 'text-ink-muted hover:text-ink hover:bg-surface-muted'
            }`}
          >
            {s.label}
          </a>
        ))}
      </div>
    </nav>
  )
}
