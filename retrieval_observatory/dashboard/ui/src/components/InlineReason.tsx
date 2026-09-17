/** Visible, truncated reason for an indeterminate / not-applicable result; full text on hover. */
export default function InlineReason({ reason }: { reason: string | null | undefined }) {
  if (!reason) return null
  return (
    <span className="block max-w-[18rem] truncate text-[10px] text-amber-700 dark:text-amber-400" title={reason}>
      {reason}
    </span>
  )
}
