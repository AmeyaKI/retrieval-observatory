import { ReleaseSliceResult } from '../api'

export default function ReleaseSliceTable({
  slices,
  onGuardSelect,
  canNavigate,
}: {
  slices: ReleaseSliceResult[]
  onGuardSelect: (metric: string) => void
  canNavigate: boolean
}) {
  if (slices.length === 0) return null
  return (
    <section aria-labelledby="declared-slices-heading" className="space-y-2">
      <h3 id="declared-slices-heading" className="text-sm font-semibold text-ink">Declared slices</h3>
      <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-700">
        <table className="min-w-full text-xs">
          <thead className="bg-surface-muted text-left text-ink-faint"><tr>
            <th className="p-2">Slice</th><th className="p-2">Status</th><th className="p-2">Paired n</th><th className="p-2">Guards</th>
          </tr></thead>
          <tbody>{slices.map(slice => (
            <tr key={slice.id} className="border-t border-slate-200 dark:border-slate-700">
              <td className="p-2"><span className="font-semibold">{slice.id}</span><span className="block text-ink-faint">{slice.field} = {String(slice.value)}</span></td>
              <td className="p-2 font-semibold">{slice.status}</td>
              <td className="p-2 font-mono">{slice.paired_n}</td>
              <td className="p-2 space-x-2">{slice.guards.map(guard => (
                <button key={guard.metric} type="button" disabled={!canNavigate || !['HOLD', 'BLOCK', 'FAIL'].includes(guard.status)} onClick={() => onGuardSelect(guard.metric)} className="underline disabled:no-underline disabled:opacity-70">
                  {guard.metric} · {guard.status}
                </button>
              ))}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  )
}
