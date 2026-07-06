import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'

interface Props {
  title: string
  glossaryKey?: keyof typeof METRIC_GLOSSARY
}

export default function SectionHeading({ title, glossaryKey }: Props) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <h3 className="text-sm font-semibold text-gray-800 dark:text-slate-100">{title}</h3>
      {glossaryKey ? <MetricTooltip text={METRIC_GLOSSARY[glossaryKey]} /> : null}
    </div>
  )
}
