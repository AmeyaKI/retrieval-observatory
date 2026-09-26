import { MIGRATION_GUIDE_HREF, Workspace, workspaceLabel } from '../utils/focusedRoutes'

interface Props {
  /** The retired hash the user arrived on, e.g. `#/home`. */
  destination: string
  replacement: Workspace
  message: string
  /** Link into the retained workflow (already carrying the current scope). */
  href: string
}

/** Shown for retired destinations and unknown hashes: what went away, and the one place to go instead. */
export default function MigrationNotice({ destination, replacement, message, href }: Props) {
  const label = workspaceLabel(replacement)
  return (
    <main className="flex-1 overflow-auto p-6 sm:p-10">
      <section role="note" aria-labelledby="migration-title" className="app-card mx-auto max-w-2xl p-6">
        <p className="eyebrow">Retired destination</p>
        <h1 id="migration-title" className="mt-2 text-xl font-semibold text-ink">
          <code className="font-mono text-base">{destination}</code> is no longer a destination
        </h1>
        <p className="mt-3 text-sm leading-6 text-ink-muted">{message}</p>
        <div className="mt-5 flex flex-wrap items-center gap-4 text-sm">
          <a
            href={href}
            data-replacement={replacement}
            className="rounded-md bg-accent px-3 py-1.5 font-medium text-white hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600"
          >
            Open {label}
          </a>
          <a href={MIGRATION_GUIDE_HREF} className="text-accent underline-offset-2 hover:underline">
            Learn more
          </a>
        </div>
      </section>
    </main>
  )
}
