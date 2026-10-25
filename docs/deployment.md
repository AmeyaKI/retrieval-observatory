# Hosted demo deployment

retobs stays local-first. This page is the **optional** path that publishes a read-only
dashboard of committed demo data on Azure Container Apps. The operational record
(maintainer commands, exposure checklist and results, cost, teardown) is
[`deploy/README.md`](../deploy/README.md); this page explains what is hosted and why.

**Live URL:** https://retobs-demo.happywater-562fb4f3.westus2.azurecontainerapps.io (Azure Container Apps, westus2; first deployed 2026-09-14, rebuilt for the 0.8.0 dashboard on 2026-10-25).

## What is hosted

- Image: `ghcr.io/ameyaki/retrieval-observatory:demo`, built by the `Demo image` GitHub
  workflow from `deploy/Dockerfile`. No local Docker is needed.
- Platform: Azure Container Apps, resource group `rg-retobs-demo`, region `westus2` (chosen to satisfy the subscription's allowed-regions policy),
  scale-to-zero, one replica.
- Data: three SQLite databases, committed gzip-compressed under `deploy/data/` (about 3 MB)
  and unpacked into the image at `/data/`:
  - `scifact`: a real run, the one the site opens on. 300 SciFact test questions through
    keyword search (BM25), vector search (all-MiniLM-L6-v2) and reciprocal-rank fusion, 20
    candidates per step, scored at the top 10 (`deploy/scifact_hybrid.yaml`).
  - `demo`: the built-in `retobs demo` baseline and repaired candidate, for compare mode and Audit.
    The hosted site refuses path inputs, so Audit cannot load a release policy there and its
    decision reads HOLD ("a release policy is required"); run `retobs demo` locally for the policy decision.
  - `integration`: a small project wired through `retobs integrate` and verified, for Connect.

  `deploy/prepare_data.py` migrates each one, makes build paths relative, indexes every run
  for Investigate, and refuses any database that still holds an absolute path or an e-mail.
- Mode: `RETOBS_READ_ONLY=1`. SQLite is opened `mode=ro`, files are `chmod 444`, the process
  runs as a non-root user, every mutating route returns 403, path-typed inputs are refused,
  and a per-IP rate limit (`RETOBS_RATE_LIMIT_PER_MINUTE`, default 300) is on.
- Health: `GET /healthz` returns `{"status":"ok","read_only":true,"databases":3}`.

Why bake rather than mount: the demo is static, a storage account is one more billable
resource, and the dashboard needs SQLite rather than the JSON exports under `results/`.

## What is not changed

- The published PyPI package has no Azure dependency; `pip install retrieval-observatory`
  is unaffected. Everything deployment-specific lives in `deploy/` and the workflow.
- The root `Dockerfile` and `docker compose up` are the local path and are untouched.
- Local `retobs serve` is unchanged: with `RETOBS_READ_ONLY` unset the store is writable,
  there is no rate limit, and nothing returns 403.

## Environment variables (names only; no secrets exist)

| Variable | Set where | Meaning |
| --- | --- | --- |
| `RETOBS_READ_ONLY` | `deploy/Dockerfile`, deploy script | read-only store, 403 on writes, hidden paths |
| `RETOBS_RATE_LIMIT_PER_MINUTE` | `deploy/Dockerfile`, deploy script | per-IP limit; `0` disables |
| `RETOBS_DASHBOARD_DBS` | `deploy/Dockerfile` | colon-separated baked database paths |

## Deploy, verify, tear down

See [`deploy/README.md`](../deploy/README.md). In short: let the workflow publish the image,
make the GHCR package public once, then `az login` and `./deploy/deploy_azure.sh`. Tear down
with `az group delete --name rg-retobs-demo --yes`.

## Fallback

If Container Apps is blocked by quota or policy, use Azure App Service for Containers with
the same image and port 8000; if Azure is blocked entirely, AWS App Runner with the same
GHCR image. Record which path worked in `deploy/README.md` and on this page.
