interface Props {
  warnings: string[]
  className?: string
}

/** Run-level data quality warnings from GET /runs/{id}/overview */
export default function DataQualityWarnings({ warnings, className = '' }: Props) {
  if (warnings.length === 0) return null

  return (
    <div
      className={`mb-4 p-3 border border-amber-300 rounded-lg bg-amber-50 ${className}`}
      data-testid="data-quality-warnings"
    >
      <div className="text-xs font-semibold text-amber-800 mb-2">Data Quality Warnings</div>
      <ul
        role="list"
        className="m-0 pl-5 space-y-2 list-disc list-outside [list-style-position:outside]"
      >
        {warnings.map((w, i) => (
          <li
            key={`${i}-${w.slice(0, 48)}`}
            className="list-item text-xs leading-relaxed text-amber-800 break-words [overflow-wrap:anywhere]"
          >
            {w}
          </li>
        ))}
      </ul>
    </div>
  )
}
