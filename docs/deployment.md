# Hosted demo deployment

retobs stays local-first. This page is the **optional** path that publishes a read-only
dashboard of the committed BEIR sweep on Azure Container Apps. The operational record
(owner commands, exposure checklist and results, cost, teardown) is
[`deploy/README.md`](../deploy/README.md); this page explains what is hosted and why.

**Live URL:** https://retobs-demo.happywater-562fb4f3.westus2.azurecontainerapps.io (deployed 2026-09-14, Azure Container Apps, westus2).

## What is hosted

- Image: `ghcr.io/ameyaki/retrieval-observatory:demo`, built by the `Demo image` GitHub
  workflow from `deploy/Dockerfile`. No local Docker is needed.
- Platform: Azure Container Apps, resource group `rg-retobs-demo`, region `westus2` (Azure for Students region policy), scale-to-zero, one replica.
- Data: three SQLite databases baked into the image at `/data/` (nfcorpus `37d3a79c`,
  scifact `49b423cf`, fiqa `0784ed30`), about 53 MB, prepared by `deploy/prepare_data.py`
  and committed under `deploy/data/`.
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
GHCR image. Record which path worked in `deploy/README.md` and `HANDOFF.md`.
