interface Props {
  className?: string
}

export default function WorkspaceGlossaryLink({ className = 'text-[11px] underline' }: Props) {
  return (
    <a href="#/glossary" className={className}>
      Glossary
    </a>
  )
}
