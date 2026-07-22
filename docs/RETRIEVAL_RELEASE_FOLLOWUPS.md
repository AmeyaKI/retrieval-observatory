# Retrieval release decision follow-up audit

This ledger records issues found while implementing Tasks 1–13 and their status after the end-of-plan review on 2026-07-22. “Resolved” means code and focused regression coverage are present. “Compatibility window” means the behavior is deliberately retained for one release. “Deferred contract” means RetObs blocks or labels the unsupported claim instead of fabricating evidence.

## Before Task 2

- **Resolved — explicit lineage-gated promotion.** `evidence.promotion.require_lineage_readiness` now applies the declared lineage-diagnosis requirements to promotion only when explicitly enabled (`18a5441`). Promotion and diagnosis remain independent by default.

## Before Task 3

- **Resolved — independent lineage schema version.** New traces carry `lineage_schema_version=2` while the public trace envelope remains schema version 1; legacy payloads without the field deserialize as lineage v1 (`21c2bf5`).
- **Resolved — recorded native exit evidence.** Native DAG filter drop reasons now populate `decision_reason` with `decision_evidence="recorded"`; operator-type guesses remain `legacy_inferred` (`4b9f0c8`).

## Evidence and policy

- **Resolved — run-window telemetry history.** Both stores accept bounded health reads and evaluation completion selects a snapshot from the run window instead of the latest service snapshot (`609d3fa`).
- **Resolved — document identity coverage.** Evidence profiles measure stable logical-chunk plus document revision/content-hash coverage, and incomplete coverage blocks lineage diff rather than promotion (`21c2bf5`).
- **Resolved — reviewed equivalent stages.** Policies accept exact one-to-one baseline/candidate operator mappings; assessment normalizes only those reviewed IDs and undeclared semantic changes still block (`39e2c2b`).
- **Open deferred contract — declared-slice population coverage.** Metric rows support exact declared-slice pairing and expose paired-row coverage, but `run_queries` does not yet persist query metadata or a complete judged-negative population. RetObs therefore cannot distinguish every unjudged slice query from every non-emitted metric row. Expanding the run-query/qrel persistence schema is required before calling this population coverage.

## Trace and adapter contracts

- **Resolved — explicit branch identity.** `OperatorSpan.branch_id` is serialized directly, with `params.branch_id` retained as a legacy fallback (`4b9f0c8`).
- **Resolved — trace-qualified API composition.** Query APIs preserve trace and pipeline identity and use trace-qualified node IDs; equal candidate IDs are not merged across traces (`bc30ecb`, `210751d`).
- **Resolved — ambiguous cross-run pairing.** The diff endpoint pairs unique shared `request_id` values when multiple trace instances exist; otherwise it blocks and returns every unpaired graph instead of selecting an arbitrary trace (`c3a9257`).
- **Open deferred contract — multi-span OTel topology envelope.** The dependency-light adapter maps one explicit retrieval span and marks missing parents, inputs, or exits partial. A reviewed multi-span correlation envelope is still required before external spans can count as complete recorded topology.
- **Open deferred contract — validated qrel-to-chunk population mapping.** The read model and API consume explicit mapping completeness and refuse upstream-loss claims without it. Native evaluation does not yet persist a corpus-wide document-to-chunk mapping artifact, so manually absent mapping evidence remains `None`/blocked rather than inferred from document qrels.

## Artifact, API, and Explorer

- **Resolved — configured dashboard policy.** Compare accepts an explicit local policy path and returns the same canonical decision as CLI/SDK/MCP; no browser-side release status is calculated (`4479980`).
- **Resolved — guard-specific affected queries.** Every aggregate and declared-slice guard carries its own ordered affected query IDs, which drive the investigation link (`b6a88c4`).
- **Resolved — complete static Explorer surface.** Branch, stage, outcome, evidence, and source filters; aggregate route widths; trace-qualified selection; passport rank/score/exit/source details; and evidence-bounded stage pointers are present (`ac4b267`).
- **Resolved — policy-aware lineage diff.** Reviewed stage mappings flow through dashboard comparison links into the local lineage-diff endpoint (`39e2c2b`).
- **Compatibility window — legacy candidate aliases.** `/candidate-journeys`, document-ID candidate lookup, `relevant`, TP/FP/FN/TN helper utilities, and the first-passport alias remain for one release. The new Explorer uses operational outcomes and trace-qualified nodes. Remove these aliases only in the next breaking cleanup.
- **Compatibility window — legacy CI exit aliases.** `--fail-on regression` and `regression-or-no-decision` map to `fail` and `hold-or-block-or-fail` with warnings. Remove them after one release cycle.

## Environment review

- **Open environment item — local Chromium.** Python browser assertions are committed, but local Playwright execution remains skipped when the Chromium binary is not installed. CI or release environments that rely on the browser workflow must install the pinned browser binary.

## End-of-plan conclusion

All features explicitly delivered by Tasks 1–13 are implemented and covered by the prescribed focused suites. The end-of-plan review additionally resolved the promotion-linkage flag, lineage versioning, run-window health lookup, native recorded exits, document identity coverage, explicit branches, ambiguous trace pairing, guard-specific query links, dashboard policy input, Explorer completeness, and reviewed stage mappings.

The three open items above are bounded follow-on contracts, not silent pass paths: declared-slice population completeness, corpus-wide qrel-to-chunk mapping, and multi-span standards topology remain unavailable or blocked when their evidence is absent. The two compatibility items are intentionally retained for the documented one-release window.
