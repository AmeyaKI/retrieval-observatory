// Shared op-type visual language (RETOBS_FINER_PLAN_PHASE2.md, Item B step 7). Extracted
// from PipelineDagView.tsx so every place that shows an operator -- the architecture DAG,
// candidate flow panel, attribution grid, query timeline -- colors a RERANK node the same
// way. Do not fork this map; import it.
export interface OpAccent {
  fill: string
  stroke: string
  text: string
}

export const OP_ACCENT: Record<string, OpAccent> = {
  SOURCE: { fill: 'rgba(37,99,235,0.10)', stroke: 'rgba(37,99,235,0.55)', text: 'rgb(59,130,246)' },
  FUSE: { fill: 'rgba(139,92,246,0.12)', stroke: 'rgba(139,92,246,0.60)', text: 'rgb(167,139,250)' },
  RERANK: { fill: 'rgba(217,119,6,0.12)', stroke: 'rgba(217,119,6,0.55)', text: 'rgb(245,158,11)' },
  BOOST: { fill: 'rgba(5,150,105,0.12)', stroke: 'rgba(5,150,105,0.55)', text: 'rgb(16,185,129)' },
  EXPAND: { fill: 'rgba(13,148,136,0.12)', stroke: 'rgba(13,148,136,0.55)', text: 'rgb(45,212,191)' },
  FILTER: { fill: 'rgba(220,38,38,0.12)', stroke: 'rgba(220,38,38,0.55)', text: 'rgb(248,113,113)' },
  GATE: { fill: 'rgba(202,138,4,0.12)', stroke: 'rgba(202,138,4,0.55)', text: 'rgb(234,179,8)' },
  TRANSFORM: { fill: 'rgba(79,70,229,0.12)', stroke: 'rgba(79,70,229,0.55)', text: 'rgb(129,140,248)' },
  GENERATE: { fill: 'rgba(219,39,119,0.12)', stroke: 'rgba(219,39,119,0.55)', text: 'rgb(244,114,182)' },
}

export const OP_LABEL: Record<string, string> = {
  SOURCE: 'Retrieval', FUSE: 'Fusion', RERANK: 'Reranking', BOOST: 'Boosting',
  EXPAND: 'Expansion', FILTER: 'Filtering', GATE: 'Gating', TRANSFORM: 'Transform',
  GENERATE: 'Generation',
}
