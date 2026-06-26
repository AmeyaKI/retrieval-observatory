import { METRIC_GLOSSARY } from '../../utils/metricGlossary'

// Honesty primitive: production has no ground truth, so every "failure" is a label-free
// proxy signal, shown as "suspected" with a tooltip naming the exact trigger.
const SIGNAL_LABEL: Record<string, string> = {
  empty_candidates: 'Empty candidates',
  low_confidence: 'Low confidence',
  high_churn: 'High churn (≥70%)',
  latency_over_budget: 'Latency over budget',
}

const SIGNAL_TOOLTIP: Record<string, string> = {
  empty_candidates: 'The retriever returned no documents for this query.',
  low_confidence: "The top candidate's score is at or below the confidence floor.",
  high_churn: 'A large fraction of candidates were dropped between stages (≥70%).',
  latency_over_budget: 'Total latency exceeded the service budget.',
}

export default function SuspectedFailureChip({ signal }: { signal: string }) {
  const label = SIGNAL_LABEL[signal] || signal
  const thresholdTips =
    signal === 'high_churn' ? ` ${METRIC_GLOSSARY.tracelens_high_churn_threshold}` : ''
  const tip = (SIGNAL_TOOLTIP[signal] || 'Label-free proxy failure signal.') + thresholdTips
  return (
    <span
      title={`Suspected · ${tip}`}
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-rose-200 bg-rose-50 text-rose-700 text-[10px] font-medium"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
      {label}
    </span>
  )
}
