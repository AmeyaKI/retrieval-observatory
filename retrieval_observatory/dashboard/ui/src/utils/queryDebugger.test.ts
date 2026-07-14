import { describe, expect, it } from 'vitest'
import { RetrievalTraceV2 } from '../api'
import { relevantDocumentOutcomes } from './queryDebugger'

const candidate = (doc_id: string, rank: number) => ({
  doc_id, score: 1 / rank, rank, input_rank: rank, output_rank: rank,
  origin_op_ids: ['source'], score_components: {}, add_reason: 'retrieved', drop_reason: null, metadata: {},
})

const trace: RetrievalTraceV2 = {
  trace_id: 't', run_id: 'r', query_id: 'q', query_text: 'query', pipeline_id: 'p',
  total_latency_ms: 2, status: 'OK', timestamp: '', metadata: {}, error_traceback: null, final_op_id: 'filter',
  spans: [
    { op_id: 'source', op_type: 'SOURCE', op_name: 'source', parent_ids: [], status: 'FIRED', deterministic: true, replay_policy: 'EXACT', latency_ms: 1, inputs: [], outputs: [candidate('lost', 1), candidate('kept', 2)], params: {}, gate_values: {}, input_variant: 'raw', error: null },
    { op_id: 'filter', op_type: 'FILTER', op_name: 'filter', parent_ids: ['source'], status: 'FIRED', deterministic: true, replay_policy: 'EXACT', latency_ms: 1, inputs: [candidate('lost', 1), candidate('kept', 2)], outputs: [candidate('kept', 1)], params: {}, gate_values: {}, input_variant: 'raw', error: null },
  ],
}

describe('relevantDocumentOutcomes', () => {
  it('locates measured loss at the exact operator and distinguishes misses/survivors', () => {
    const outcomes = relevantDocumentOutcomes([trace], ['lost', 'kept', 'absent'])
    expect(outcomes.find((row) => row.docId === 'lost')).toMatchObject({ outcome: 'lost', operatorId: 'filter', evidenceClass: 'measured' })
    expect(outcomes.find((row) => row.docId === 'kept')).toMatchObject({ outcome: 'survived', outputRank: 1 })
    expect(outcomes.find((row) => row.docId === 'absent')).toMatchObject({ outcome: 'never_retrieved', operatorId: null })
  })
})
