# Retrieval Observatory: engineering dossier for Rhema Health

## Purpose

This dossier accompanies two coding-agent sessions from the open-source
[Retrieval Observatory](https://github.com/AmeyaKI/retrieval-observatory)
project. It provides the context, implementation path, and a focused
technical walkthrough for a conversation about how I use coding agents to
build reliable AI infrastructure.

The two complete session exports should be shared alongside this document:

1. **Audit RetObs integration and UX** — source session ID
  `019f67d5-249c-7712-b24e-2f4dbca90dd8`
2. **Add release policy contract** — source session ID
  `019f8b00-2a84-7920-8712-92808e780794`

This is a guide to those sessions, not a replacement for their complete
transcripts.

---



## Project in one paragraph

Retrieval Observatory is an open-source reliability layer for multi-stage RAG
systems. It is designed to make retrieval behavior inspectable across
benchmarking, tracing, failure diagnosis, and regression testing. The core
problem addressed in this dossier is that a single aggregate retrieval score
is not sufficient evidence to decide whether a candidate retrieval change is
safe to promote.

---



## Development arc

```text
Audit the product and integration experience
                 |
                 v
Identify evidence, observability, and release-trust gaps
                 |
                 v
Define a bounded policy and implementation plan
                 |
                 v
Implement and test the release-decision subsystem in scoped tasks
                 |
                 v
Validate behavior with unit, integration, UI, packaging, and CI checks
```



### Session 1 — Audit RetObs integration and UX

The audit asked whether RetObs was genuinely useful to an ML/RAG engineer,
easy to wire into an existing pipeline, and capable of presenting trustworthy
diagnostic information. It evaluated the project through three lenses:

- **Integration:** could a user or agent add RetObs to an existing RAG system
with little disruption?
- **Usability:** could an engineer understand the dashboard, traces, and
investigation workflow?
- **Reliability value:** did the system distinguish meaningful evidence from
incomplete or misleading evidence?

The resulting direction was to make release decisions explicit and
evidence-aware rather than presenting evaluation output as inherently
actionable.

### Session 2 — Add release policy contract

The implementation session translated that direction into a scoped,
test-first release-reliability system. It progressed through narrowly bounded
tasks rather than an undifferentiated rewrite. Major components included:

- a bounded release-policy and claim-readiness contract;
- candidate-lineage and trace-serialization contracts;
- run-scoped identity, telemetry, topology, and lineage evidence;
- evidence-readiness assessment;
- paired per-query statistics and declared query slices;
- `PASS`, `HOLD`, `BLOCK`, and `FAIL` release decisions;
- SDK, CLI, dashboard, and CI-facing outputs;
- regression tests for incomplete, ambiguous, or invalid evidence.

The session also included an end-of-plan audit that found and addressed edge
cases not covered by happy-path tests. Those included cases where missing
telemetry, incomplete lineage evidence, partial production capture, or absent
topology data could otherwise be mistaken for positive evidence.

---



## Focus of the live walkthrough



### Policy-driven release gating for RAG changes

The live walkthrough should focus on one narrow question:

> How can a RAG system distinguish a real release decision from an
> under-measured experiment?

The implementation combines evidence validation and statistical evaluation:

```text
Baseline run + candidate run
              |
              v
Validate comparability and evidence completeness
  - run identity
  - trace / lineage capture
  - telemetry health
  - topology and candidate evidence
              |
              v
Evaluate paired per-query metrics and declared slices
              |
              v
Compose an explicit outcome
PASS | HOLD | BLOCK | FAIL
```



### Decision semantics


| Outcome | Meaning                                                                               |
| ------- | ------------------------------------------------------------------------------------- |
| `PASS`  | Required evidence is valid and supports promotion under the declared policy.          |
| `HOLD`  | Evidence is valid but insufficient or inconclusive; more measurement is needed.       |
| `BLOCK` | Policy-required evidence is missing or invalid, so the relevant claim cannot be made. |
| `FAIL`  | Valid evidence demonstrates a regression beyond the declared budget.                  |


This distinction is intentional: **unknown evidence must not silently become a
pass**.

---



## Key engineering decisions



### 1. Separate evidence quality from model/system outcome

An observed regression and an unmeasured experiment are different states. The
system does not collapse them into a generic failure or a misleading success.
For example, incomplete capture can produce `HOLD` or `BLOCK` depending on
the declared policy, while a statistically supported regression produces
`FAIL`.

### 2. Treat absent telemetry as unknown, not zero loss

A run with no observed trace attempts cannot establish a zero dropped-trace
rate. The implementation represents this as unavailable evidence rather than
defaulting it to zero.

### 3. Make slice-level regressions visible

Aggregate retrieval metrics can hide regressions for important classes of
queries. The release path supports paired per-query analysis and declared
slices so that acceptance criteria are explicit and reviewable.

### 4. Preserve reversibility and explainability

The design emits stable findings and next actions rather than only a final
boolean. This lets an engineer determine whether to fix instrumentation,
collect more evidence, inspect a problematic slice, or reject the candidate.

---



## Code to inspect during the walkthrough

The exact file layout may evolve; the relevant implementation areas are:

- `retrieval_observatory/release/policy.py` — policy schema and allowed
release requirements.
- `retrieval_observatory/release/assessment.py` — evidence readiness and
stable findings.
- `retrieval_observatory/release/statistics.py` — paired effect intervals and
guard evaluation.
- `retrieval_observatory/release/decision.py` — outcome precedence and final
release decision.
- `tests/unit/test_release_assessment.py` — incomplete-evidence and
edge-condition coverage.
- `tests/unit/test_release_statistics.py` and
`tests/integration/test_release_decision_workflow.py` — statistical and
end-to-end decision behavior.

---



## How I used coding agents

I used coding agents to navigate the codebase, implement narrowly scoped
changes, create and revise tests, surface edge cases, and iterate quickly.
The engineering work was constrained by explicit requirements:

- preserve the policy semantics and privacy/local-first constraints;
- avoid unrelated refactors;
- work task by task;
- use focused failing tests before implementation where appropriate;
- validate the resulting behavior instead of treating generated code as
correct by default;
- record limitations rather than claiming unsupported guarantees.

The useful measure of agent-assisted engineering here is not the volume of
generated code. It is whether the resulting system has clear constraints,
testable behavior, inspectable tradeoffs, and an honest boundary around what
the evidence can support.

---



## Validation and limitations

Before sharing, replace this section with the latest, reproducible commands
and their exact results from the repository's current default branch.

Validation should include only results that can be freshly reproduced, such
as focused release-decision tests, the relevant integration test, linting, and
the project CI run.

Known limitations to state plainly:

- A release decision is only as good as the declared policy and recorded
evidence.
- A `PASS` supports promotion under that policy; it does not prove universal
safety, clinical correctness, or production readiness.
- Sensitive deployments require additional operational controls beyond a
local observability library, including access control, retention controls,
and data-governance safeguards.

---



## Proposed 20-minute discussion

1. **Problem and product context** — 2 minutes
2. **Audit finding: why a score alone is insufficient** — 3 minutes
3. **Evidence and policy architecture** — 4 minutes
4. **Walk through release assessment and decision code** — 5 minutes
5. **Tests: missing evidence, partial capture, and regression behavior** — 4 minutes
6. **Limitations and what I would improve next** — 2 minutes



### Questions I expect to be able to answer

- Why should a missing signal block a release rather than be treated as zero?
- How is `HOLD` materially different from `FAIL`?
- Why use paired per-query analysis instead of only aggregate metrics?
- Which policy requirements should be mandatory for a high-stakes workflow?
- What would need to change before using this approach with sensitive clinical
data?

---



## Scope and provenance

This dossier concerns the public Retrieval Observatory project only. It does
not include code, data, metrics, transcripts, or implementation details from
private internship work.