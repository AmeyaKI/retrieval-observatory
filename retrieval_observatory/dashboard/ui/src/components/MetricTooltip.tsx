import { useEffect, useRef, useState } from 'react'

interface Props {
  text: string
  /** Position the popover to the left instead of right (for rightmost columns) */
  alignLeft?: boolean
}

export function MetricTooltip({ text, alignLeft = false }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  return (
    <span ref={ref} className="relative inline-block align-middle ml-1">
      <button
        className="w-4 h-4 rounded-full bg-gray-200 dark:bg-slate-700 hover:bg-gray-300 text-gray-500 dark:text-slate-400 hover:text-gray-700 text-[10px] font-bold leading-none flex items-center justify-center transition-colors"
        onClick={() => setOpen((v) => !v)}
        aria-label="Explain this metric"
        type="button"
      >
        ?
      </button>
      {open && (
        <div
          className={`absolute z-50 w-72 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-lg shadow-lg p-3 text-xs text-gray-600 dark:text-slate-300 leading-relaxed ${
            alignLeft ? 'right-0' : 'left-0'
          } top-6`}
        >
          <button
            className="absolute top-1.5 right-2 text-gray-400 dark:text-slate-500 hover:text-gray-600"
            onClick={() => setOpen(false)}
            type="button"
          >
            ×
          </button>
          {text}
        </div>
      )}
    </span>
  )
}
