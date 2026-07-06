interface Props {
  label: string
}

export default function NoData({ label }: Props) {
  return (
    <div className="rounded border border-dashed border-gray-300 dark:border-slate-600 bg-gray-50 dark:bg-slate-800/60 p-3 text-xs text-gray-600 dark:text-slate-300">
      {label}
    </div>
  )
}
