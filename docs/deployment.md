# Hosted demo deployment

RetObs stays local-first. This page is the **optional** path that publishes a
read-only dashboard of the committed BEIR sweep.

**Live URL:** not deployed yet — follow the steps below, then replace this line
with `https://<your-fqdn>`.

## What is hosted

- Image: `ghcr.io/ameyaki/retrieval-observatory:demo`
- Platform: Azure Container Apps, resource group `rg-retobs-demo`
- Data: SQLite copies of the BEIR publish sweep, **baked into the image**
  (nfcorpus `37d3a79c`, scifact `49b423cf`, fiqa `0784ed30`).
- Image size at last local build: ~51 MB of SQLite data plus the app image
  (well under the 2 GB gate; Cohere partial DB omitted).
- Why bake, not mount: static demo; no extra storage account; dashboard
  requires SQLite, not the JSON under `results/`.

The published PyPI package is unchanged. There is no Azure SDK dependency.

## Prerequisites

- Docker
- Azure CLI (`az`) and a subscription with free or student credits
- A GitHub token that can `docker push` to GHCR
- Local BEIR SQLite files (see `results/RESULTS_OVERVIEW.md`)

## Rebuild and push

```bash
mkdir -p deploy/data
cp .retobs/publish_sweep_nfcorpus.db deploy/data/nfcorpus.db
cp .retobs/publish_sweep_scifact.db deploy/data/scifact.db
cp .retobs/publish_sweep_fiqa.db deploy/data/fiqa.db
docker build -f deploy/Dockerfile -t retobs:demo .
docker tag retobs:demo ghcr.io/ameyaki/retrieval-observatory:demo
docker push ghcr.io/ameyaki/retrieval-observatory:demo
```

Make the GHCR package **public** (Package settings → Change visibility) so
Azure can pull without registry secrets.

## Deploy (Azure Container Apps)

```bash
az login
az account set --subscription "<subscription-id>"

az group create --name rg-retobs-demo --location eastus

az containerapp env create \
  --name retobs-demo-env \
  --resource-group rg-retobs-demo \
  --location eastus

az containerapp create \
  --name retobs-demo \
  --resource-group rg-retobs-demo \
  --environment retobs-demo-env \
  --image ghcr.io/ameyaki/retrieval-observatory:demo \
  --target-port 8000 \
  --ingress external \
  --cpu 0.5 \
  --memory 1.0Gi \
  --min-replicas 0 \
  --max-replicas 1 \
  --env-vars RETOBS_READ_ONLY=1

az containerapp show \
  --name retobs-demo \
  --resource-group rg-retobs-demo \
  --query properties.configuration.ingress.fqdn \
  --output tsv
```

Required env vars (names only):

- `RETOBS_READ_ONLY` — set to `1` on the host
- `RETOBS_DASHBOARD_DBS` — already set in `deploy/Dockerfile`

No connection strings. No API keys.

### Verify after deploy

```bash
FQDN="$(az containerapp show -n retobs-demo -g rg-retobs-demo --query properties.configuration.ingress.fqdn -o tsv)"
curl -sS "https://${FQDN}/dbs"
```

Expected: JSON with three databases. Open `https://${FQDN}` in a browser and
confirm NFCorpus run `37d3a79c`.

## Cost

- Idle: scale to zero (`--min-replicas 0`). Expect **$0** compute when nobody
  hits the URL.
- Cold start on first request after idle.
- Log Analytics may incur a small residual. Check usage in the Azure portal or:

```bash
az consumption usage list --start-date <today-30> --end-date <today>
```

Stay on the free / student / trial credit subscription.

## Teardown

```bash
az containerapp delete --name retobs-demo --resource-group rg-retobs-demo --yes
az containerapp env delete --name retobs-demo-env --resource-group rg-retobs-demo --yes
az group delete --name rg-retobs-demo --yes
```

Deleting the resource group removes the app, environment, and logs. The GHCR
image remains until you delete the GitHub package; it does not bill Azure.

## Fallback

If Container Apps fails (quota, provider, policy), try **Azure App Service for
Containers** with the same image and port 8000. If Azure is blocked entirely,
use **AWS App Runner** with the same GHCR image. Record which path worked in
this file.

## Local-first (unchanged)

```bash
docker compose up
# or
retobs serve --db .retobs/results.db
```

The root `Dockerfile` and `docker-compose.yml` are unchanged. The deploy image
is only `deploy/Dockerfile`.
