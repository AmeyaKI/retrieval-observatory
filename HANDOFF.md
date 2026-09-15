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

### Phase B starts with

`results/study/PREREGISTRATION.md`, committed before any grid cell runs. Open questions for the owner before writing it: how `GATE` and `EXPAND` operators map onto the brief's operator classes (the brief lists fusion, rerank, filter/dedup, routing/merge, other; the HotpotQA pipeline's richest lineage sits in `EXPAND` and `GATE` spans).
