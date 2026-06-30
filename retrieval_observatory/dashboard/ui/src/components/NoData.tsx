interface Props {
  label: string
}

export default function NoData({ label }: Props) {
  return (
    <div className="rounded border border-dashed border-gray-300 bg-gray-50 p-3 text-xs text-gray-600">
      {label}
    </div>
  )
}
