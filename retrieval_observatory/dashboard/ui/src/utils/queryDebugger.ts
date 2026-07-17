import { RetrievalTrace } from '../api'

export interface RelevantDocumentOutcome {
  docId: string
  traceId: string
  pipelineId: string
  outcome: 'lost' | 'never_retrieved' | 'survived'
  operatorId: string | null
  inputRank: number | null
  outputRank: number | null
  evidenceClass: 'measured'
}

export function relevantDocumentOutcomes(
  traces: RetrievalTrace[],
  relevantDocIds: string[],
): RelevantDocumentOutcome[] {
  return traces.flatMap((trace) => relevantDocIds.map((docId) => {
    let observed = false
    for (const span of trace.spans) {
      const input = (span.inputs ?? []).find((candidate) => candidate.doc_id === docId)
      const output = (span.outputs ?? []).find((candidate) => candidate.doc_id === docId)
      if (output) observed = true
      if (input && !output) {
        return {
          docId,
          traceId: trace.trace_id,
          pipelineId: trace.pipeline_id,
          outcome: 'lost' as const,
          operatorId: span.op_id,
          inputRank: input.input_rank ?? input.rank ?? null,
          outputRank: null,
          evidenceClass: 'measured' as const,
        }
      }
    }
    const finalSpan = trace.spans.find((span) => span.op_id === trace.final_op_id)
    const finalCandidate = (finalSpan?.outputs ?? []).find((candidate) => candidate.doc_id === docId)
    return {
      docId,
      traceId: trace.trace_id,
      pipelineId: trace.pipeline_id,
      outcome: observed && finalCandidate ? 'survived' as const : 'never_retrieved' as const,
      operatorId: null,
      inputRank: null,
      outputRank: finalCandidate?.output_rank ?? finalCandidate?.rank ?? null,
      evidenceClass: 'measured' as const,
    }
  }))
}
