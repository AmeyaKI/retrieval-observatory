# Hand-off

Written per `STUDY_BRIEF.md`. One section per phase; each is appended when the phase completes.

## Phase A — consolidation and hosted demo (completed 2026-09-14, release 0.6.0)

### What shipped

| Step | Commit | Summary |
| --- | --- | --- |
| A2 surface reduction | `f4b740a` | `advisor`, `forge`, `diagram`, `classifier` moved to `retrieval_observatory.experimental`; old import paths resolve to the same modules with a `DeprecationWarning`; `retobs classifier` CLI unregistered (no label source); six guides moved to `docs/guides/experimental/` |
| A1 README | `3ebec83` | Leads with "which stage earned or destroyed your metric, with attribution you can audit", the Scenario D lineage trace, install, `retobs demo`; new "Attribution you can audit" section |
| A3 hosted dashboard | `d6f2d84`, `108aceb`, `311f45d` | Read-only SQLite (`mode=ro`), non-root image, per-IP rate limit, `/healthz`, 403 on path-typed inputs, 422 on malformed parameters, hardened `.dockerignore`, baked databases committed, GHCR build workflow, one-command Azure script, `deploy/README.md` checklist with results |
| A4 release | this commit | 0.6.0 |

### Deployment

- **Provider: Azure Container Apps** (resource group `rg-retobs-demo`, region `westus2`, scale-to-zero, subscription "Azure for Students"). This is the word for the resume skills line.
- **URL:** https://retobs-demo.happywater-562fb4f3.westus2.azurecontainerapps.io
- Image: `ghcr.io/ameyaki/retrieval-observatory:demo`, built by `.github/workflows/demo-image.yml`; public package.
- Verified live on 2026-09-14: `/healthz` reports `read_only: true` with 3 databases, `/dbs` shows basenames only, a `POST` returns 403, the SPA and run metrics load.
- The two authenticated steps the owner runs (already done once; repeat after image rebuilds):

  ```bash
  az login
  ./deploy/deploy_azure.sh
  ```

- Two subscription-specific facts the script now handles: the `Microsoft.App` and `Microsoft.OperationalInsights` providers were unregistered, and the student subscription's region policy allows only centralus, mexicocentral, westus2, canadacentral, and southcentralus.

### Headline numbers

Phase A produces no study numbers. The README's Scenario D figures (recall@10 +0.0088, 95% CI [+0.0019, +0.0181], n=400) render from `results/flagship_demo/reports/scenario-a-improvement.json` and were not re-measured in this phase.

### Tests

| | Passed | Skipped |
| --- | --- | --- |
| Before Phase A (0.5.6) | 645 | 13 |
| After Phase A (0.6.0) | 658 | 13 |

New tests: experimental import shims (6), removed `classifier` command (1), read-only store, rate limit, `policy_path` rejection, `/healthz`, parameter validation (6).

### Skipped, subsampled, or deviated from the brief

- **Do-not-touch list touched minimally.** `dashboard/`, `mcp/`, `sdk/`, `store/`, `runner/`, `evidence/`, `metrics/` had import lines rewritten for the move. `store/sqlite.py` and `dashboard/api.py` also gained the read-only and hardening changes A3 explicitly requires.
- **`forge` is only partly demotable.** The public `retobs testsets` CLI and SDK `generate_testset`/`TestSet` remain public and are backed by `experimental.forge`.
- **Classifier demoted rather than fixed.** Nothing in the current runner computes a `difficulty_bucket`; restoring training needs a bucketing rule, which is a design decision, not a 30-minute fix.
- **Provider is Azure, not Fly/Render.** Decided 2026-09-10 with the owner; `STUDY_BRIEF.md` A3 amended.
- **No local Docker build.** Docker was not running on the owner's machine; the image is built and smoke-tested in GitHub Actions instead.
- **`STUDY_BRIEF.md` and `CLOUD_DEPLOY_BRIEF.md` are gitignored and untracked.** Edits to them exist only on the owner's disk. Whether to publish them is the owner's call.
- **One pre-existing bug fixed outside the brief's scope:** `GET /dbs/{db}/runs/{run}/traces` always failed response validation (declared dict, returned list).

## Interlude — adversarial review and fix cycle (2026-09-15 to 2026-09-16, unreleased on main)

Six review agents audited tracing, pipeline/runner, statistics/release, store/dashboard, integrations/MCP, and every markdown file that logs known issues, verifying each finding by running code. 52 defects were confirmed and fixed in five packages merged on `main` (WP1 `3a8ce21`, WP3 `c28ad1a`, WP2 `289d162`, WP4 `6c5d376`, WP5 `18bde48`), each with regression tests. Full list: `CHANGELOG.md` [Unreleased]. The headline ones:

- Nine of eleven MCP tools were uncallable from a real client (wrapper lost their signatures).
- `integrate --phase apply` produced no trace, so `verify` could never reach `ready`; it now bridges the recorder and decorator contexts and wraps the entrypoint with `@trace_scope`.
- Counterfactual replay overwrote a child operator's recorded outputs; it is now strict (indeterminate when a child would have to decide on unseen documents) and the runner declares a replay tier on every span (previously all NOT_REPLAYABLE).
- Gate-skipped branches scored 0 per skipped query; branch metrics are now on served queries.
- Queries that failed in only one run vanished from paired comparisons; a `min_pair_coverage` guard (0.95) returns HOLD.
- Caches ignored the corpus; a node's configured `k` was recorded but not applied; the compare page inverted per-query delta signs; production monitoring pages read fields the API never sent; graded nDCG used exponential gain while claiming BEIR parity.

Owner decisions taken during the cycle: strict replay; bridge + entrypoint for apply; served-query branch metrics; linear-gain nDCG; no BM25 zero-score padding; pairing-coverage HOLD.

### Flagship demo rerun on the fixed build (2026-09-16)

All five scenarios were rerun (`results/flagship_demo/.retobs/demo.db`, runs a1389d37 baseline, 0e39c15f wider-merge, cb269926 no-bm25, 53e6bc51 swapped-embedding, 58d239bb stale-index) and the reports regenerated.

| Scenario | Verdict | Effect on recall@10 | 95% CI | n | Reproduces published? |
| --- | --- | --- | --- | --- | --- |
| A wider merge | PASS | +0.0088 | [+0.0019, +0.0181] | 400 | exactly |
| B keyword lane disabled | PASS | +0.0300 | [+0.0056, +0.0563] | 400 | exactly |
| C swapped embedding, same index id | BLOCK | 0.0000 | [-0.0175, +0.0188] | 400 | exactly |
| C2 stale index | HOLD | -0.0212 | [-0.0394, -0.0025] | 400 | exactly |

Scenario D picks the same query (5abccf6755429965836004ab) with an identical lineage; the README trace is unchanged. What changed: branch rows. The published funnel's `rerank 0.4288 → 0.9050` was a routing-share artifact; on served queries the baseline reranker scores 0.9171 (n=187), the candidate 0.9050 (n=400), and on the 187 paired queries 0.890 with no significant difference. `CASE_STUDY.md` Act three is rewritten on these numbers. Latency medians this run: 608 ms → 865 ms; total runtime rose (317 s → 352 s), which contradicts the earlier "total runtime drops" claim, and the case study now says so.

Environment note: on this machine torch and faiss each load an OpenMP runtime and the dense lane segfaults (also on 0.6.0); `run_demo.sh` now sets `KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1`.

### Tests after the cycle

| | Passed | Skipped |
| --- | --- | --- |
| Before (0.6.0) | 658 | 13 |
| After | 866 | 13 |

### Phase B starts with

`results/study/PREREGISTRATION.md`, committed before any grid cell runs. Open questions for the owner before writing it: how `GATE` and `EXPAND` operators map onto the brief's operator classes (the brief lists fusion, rerank, filter/dedup, routing/merge, other; the HotpotQA pipeline's richest lineage sits in `EXPAND` and `GATE` spans).
