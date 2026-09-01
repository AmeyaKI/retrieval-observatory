# Hosted demo deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the existing RetObs dashboard on a public Azure URL, read-only, showing the pre-computed BEIR sweep — without turning RetObs into a cloud product.

**Architecture:** Keep the root `Dockerfile` and `docker-compose.yml` as the local-first path. Add a **deploy-only** image that copies local BEIR SQLite files into the image and starts `retobs serve` with `RETOBS_READ_ONLY=1`. Push that image to GHCR. Run it on Azure Container Apps (consumption, public ingress, scale-to-zero). Document the exact commands in `docs/deployment.md` and link the live URL from the README.

**Tech Stack:** existing FastAPI dashboard, existing `Dockerfile` as the local baseline, `deploy/Dockerfile` for the hosted image, GitHub Container Registry, Azure Container Apps, Azure CLI (`az`).

## Global Constraints

- Local-first stays the documented primary mode. This is one optional hosted demo path.
- Do not add cloud SDKs or cloud credentials to `pip install retrieval-observatory`. Core `pyproject.toml` dependencies stay unchanged.
- Do not bump the package version or publish to PyPI.
- No secrets in the repo. Document env var **names** only.
- Hosted instance is read-only: no new benchmark runs, no trace ingest that grows the demo dataset.
- Existing test suite stays green. Local `docker-compose up` works exactly as before.
- Cost: free tier / Azure student or trial credits only. Document expected cost and teardown.
- If Azure is the wrong fit, stop and switch to AWS rather than forcing it. Either token closes the resume gap.

---

## What this is (plain English)

Today everything runs on your laptop. The resume has no cloud line. This work puts **one public URL** on the internet that opens the same dashboard, already filled with the BEIR numbers you already computed.

It does **not** run live benchmarks in the cloud. That would cost money and accept untrusted work.

It does **not** change what `pip install retrieval-observatory` does.

---

## Facts already true in this repo (do not rediscover)

1. `Dockerfile` already builds the app, exposes port **8000**, and runs `retobs serve --host 0.0.0.0 --port 8000`.
2. `retobs serve` defaults to `.retobs/results.db` if you pass no `--db` and no `RETOBS_DASHBOARD_DBS`. That file is not in the image. The current container therefore starts an **empty** dashboard unless you give it a database.
3. The dashboard **only** reads SQLite (or Postgres). It does **not** load `results/nfcorpus/metrics.json`.
4. The BEIR JSON under `results/` **is** committed. The SQLite files that actually power the dashboard **are not**:
   - `.retobs/publish_sweep_nfcorpus.db` — run `37d3a79c`
   - `.retobs/publish_sweep_scifact.db` — run `49b423cf`
   - `.retobs/publish_sweep_fiqa.db` — run `0784ed30`
   - (optional) `.retobs/publish_cohere_nfcorpus.db` — run `a6dad22f`, partial
5. `*.db` and `.retobs/` are gitignored. **Never commit those files.**
6. Dashboard UI uses POST only for `/compare` and `/compare/config-diff`. Those are reads of existing runs. Everything that *creates* runs or traces must be blocked on the host.
7. `create_app(..., enable_uploads=True)` is the default. `retobs serve` does not turn uploads off.
8. Root `.gitignore` ignores most `*.md` except listed `docs/` trees. Plans live under `docs/superpowers/` (allowlisted).

## Decisions locked by this plan

| Question | Decision | Why |
|---|---|---|
| Cloud | **Azure Container Apps** first | Brief target. Consumption + public URL + scale to zero is the cheapest simple path. |
| If ACA fights us | Azure App Service for Containers, then AWS App Runner | Brief: a working AWS URL beats a stalled Azure one. |
| Registry | **GHCR** (`ghcr.io/ameyaki/retrieval-observatory:demo`) | Free. No extra Azure registry bill. The Azure token comes from **where it runs**. |
| Artifacts | **Bake SQLite into the deploy image** | Dashboard cannot show JSON exports. Baking is what the brief prefers for a static demo. |
| Local Docker | **Do not change** root `Dockerfile` CMD or `docker-compose.yml` | Constraint: local compose stays identical. |
| Read-only | Env `RETOBS_READ_ONLY=1` inside FastAPI | No cloud dependency. Local default stays writable. |
| Auth / multi-tenant | **None** | Explicitly out of scope. |

**Image-size gate:** after the first deploy-image build, if the image is **over ~2 GB**, drop the Cohere DB and re-record the decision in `docs/deployment.md`. Do not invent object storage unless the three sweep DBs alone blow that budget.

---

## File map

**Create**

- `docs/deployment.md` — how to rebuild, push, deploy, cost, teardown.
- `deploy/Dockerfile` — hosted image only.
- `deploy/.dockerignore` — keep the deploy build small and secret-free.
- `deploy/.gitignore` — ignore `deploy/data/*.db`.
- `deploy/data/.gitkeep` — empty folder so the path exists.
- `tests/unit/test_dashboard_read_only.py` — read-only guard.

**Modify**

- `retrieval_observatory/dashboard/api.py` — honor `RETOBS_READ_ONLY`.
- `README.md` — live demo link above the fold.
- `CHANGELOG.md` — two `[Unreleased]` lines.
- `.gitignore` — already allowlists `docs/superpowers/**/*.md`.

**Do not modify**

- `pyproject.toml` dependencies
- `docker-compose.yml`
- Root `Dockerfile` behavior (no new default `--db`, no cloud bits)
- Package version

**Not in git (local only)**

- `deploy/data/*.db` — copies of the three (or four) BEIR SQLite files

---

### Task 1: Confirm the BEIR databases exist on this machine

**Files:** none (read-only check)

**Interfaces:**
- Consumes: local files listed in `results/RESULTS_OVERVIEW.md`
- Produces: a yes/no on whether we can bake the real BEIR demo, or must regenerate

- [ ] **Step 1: List the expected SQLite files**

Run:

```bash
ls -lh \
  .retobs/publish_sweep_nfcorpus.db \
  .retobs/publish_sweep_scifact.db \
  .retobs/publish_sweep_fiqa.db \
  .retobs/publish_cohere_nfcorpus.db
```

Expected if the original sweep machine is this one: three (or four) files, sizes printed.

Expected if they are missing:

```text
ls: .retobs/publish_sweep_nfcorpus.db: No such file or directory
```

- [ ] **Step 2: If they are missing, stop and say so**

Do **not** silently switch to `retobs demo` / flagship HotpotQA. The brief is the BEIR run (4 pipelines, 1,271 queries, 3 datasets).

If missing, the owner regenerates locally (slow, not part of the hosted bill):

```bash
pip install -e ".[demo,dashboard,dense]"
./scripts/run_beir_publish.sh full-sweep
```

That writes the `.retobs/publish_sweep_*.db` files. Then resume this plan.

- [ ] **Step 3: Copy them into the deploy data folder (not git)**

```bash
mkdir -p deploy/data
cp .retobs/publish_sweep_nfcorpus.db deploy/data/nfcorpus.db
cp .retobs/publish_sweep_scifact.db deploy/data/scifact.db
cp .retobs/publish_sweep_fiqa.db deploy/data/fiqa.db
# only if present and size still looks reasonable:
# cp .retobs/publish_cohere_nfcorpus.db deploy/data/cohere_nfcorpus.db
ls -lh deploy/data
```

- [ ] **Step 4: Commit nothing from `deploy/data/`**

```bash
git check-ignore -v deploy/data/nfcorpus.db
```

Expected: ignored by `deploy/.gitignore` (created in Task 3) or by root `*.db`.

---

### Task 2: Prove the stock image builds (local-first, no demo data)

**Files:** none unless the build is broken — then fix **only** what blocks a successful `docker build`.

**Interfaces:**
- Consumes: root `Dockerfile`
- Produces: a known-good local image named `retobs:local`

- [ ] **Step 1: Build the existing Dockerfile**

```bash
docker build -t retobs:local .
```

Expected: exit 0. First build is slow (pip + optional UI npm build).

If it fails, fix the failure. Do not add demo DBs to this Dockerfile.

- [ ] **Step 2: Run it the way compose does**

```bash
docker run --rm -p 8000:8000 --name retobs-stock retobs:local
```

Expected log includes:

```text
Dashboard: http://localhost:8000
```

It may also warn about a missing `.retobs/results.db` or create/open an empty default DB. That is **current** behavior. Do not “fix” it in the root Dockerfile.

- [ ] **Step 3: In a second terminal, hit health**

```bash
curl -sS -o /tmp/retobs-dbs.json -w "%{http_code}\n" http://127.0.0.1:8000/dbs
```

Expected: `200`. Body is a JSON list (maybe empty or one empty default). Ctrl-C the container when done.

- [ ] **Step 4: Confirm compose still starts (do not change the compose file)**

```bash
docker compose up --build -d
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/dbs
docker compose down
```

Expected: `200`, then compose stops.

---

### Task 3: Add deploy-only Docker files (no Python yet)

**Files:**
- Create: `deploy/.gitignore`
- Create: `deploy/data/.gitkeep`
- Create: `deploy/.dockerignore`
- Create: `deploy/Dockerfile`

**Interfaces:**
- Consumes: Task 1 `deploy/data/*.db`, root app source
- Produces: an image recipe that sets `RETOBS_DASHBOARD_DBS` and `RETOBS_READ_ONLY`

- [ ] **Step 1: Write `deploy/.gitignore`**

```gitignore
data/*.db
```

- [ ] **Step 2: Write `deploy/data/.gitkeep`**

Empty file.

- [ ] **Step 3: Write `deploy/.dockerignore`**

Used when the **build context is the repo root** (`docker build -f deploy/Dockerfile .`). Docker reads `.dockerignore` from the context root, so also write this **same list** to a root file only if a root `.dockerignore` does not already exist. Prefer **one** root `.dockerignore` with:

```dockerignore
.git
.github
.venv
.pytest_cache
.mypy_cache
.ruff_cache
.coverage
htmlcov
node_modules
.retobs
.archive
.prompts
.claude
.env
**/.env
*.pyc
__pycache__
.DS_Store
tests
docs
*.md
!README.md
```

Do **not** ignore `deploy/data/*.db` — the deploy image must copy them.

If adding a root `.dockerignore` makes `docker compose build` skip something compose needs, delete the root file and keep only `deploy/.dockerignore` **and** pass:

```bash
docker build -f deploy/Dockerfile --ignorefile deploy/.dockerignore .
```

(`--ignorefile` needs Docker Buildx recent enough; if missing, use the root `.dockerignore`.)

- [ ] **Step 4: Write `deploy/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV RETOBS_READ_ONLY=1
ENV RETOBS_DASHBOARD_DBS=/data/nfcorpus.db:/data/scifact.db:/data/fiqa.db

COPY . .
RUN pip install --no-cache-dir -e ".[dashboard]"

RUN if [ -d "retrieval_observatory/dashboard/ui" ] && [ -f "retrieval_observatory/dashboard/ui/package.json" ]; then \
        apt-get update && apt-get install -y --no-install-recommends nodejs npm && \
        cd retrieval_observatory/dashboard/ui && npm ci && npm run build && \
        apt-get purge -y nodejs npm && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*; \
    fi

COPY deploy/data/nfcorpus.db deploy/data/scifact.db deploy/data/fiqa.db /data/

EXPOSE 8000

CMD ["retobs", "serve", "--host", "0.0.0.0", "--port", "8000"]
```

If you included `cohere_nfcorpus.db`, add it to `COPY` and append `:/data/cohere_nfcorpus.db` on `RETOBS_DASHBOARD_DBS`.

- [ ] **Step 5: Commit the deploy scaffolding (no `.db` files)**

```bash
git add deploy/.gitignore deploy/data/.gitkeep deploy/Dockerfile
git add .dockerignore
git status
git commit -m "$(cat <<'EOF'
Add deploy-only image recipe for the hosted dashboard demo.

EOF
)"
```

Confirm `git status` does **not** list `deploy/data/*.db`.

---

### Task 4: Read-only mode (tests first)

**Files:**
- Create: `tests/unit/test_dashboard_read_only.py`
- Modify: `retrieval_observatory/dashboard/api.py` (inside `create_app`, after `app` exists)

**Interfaces:**
- Consumes: `os.environ["RETOBS_READ_ONLY"]`
- Produces: GET `/dbs` still 200; POST `/compare` still works; POST `/dbs/{db_id}/runs` returns 403 with `{"detail": "Hosted demo is read-only"}`

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry


def _client(tmp_path, monkeypatch, read_only: str | None) -> TestClient:
    db_path = tmp_path / "demo.db"
    db_path.touch()
    if read_only is None:
        monkeypatch.delenv("RETOBS_READ_ONLY", raising=False)
    else:
        monkeypatch.setenv("RETOBS_READ_ONLY", read_only)
    app = create_app(registry=DbRegistry([str(db_path)]), enable_uploads=True)
    return TestClient(app)


def test_read_only_allows_get_dbs(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "1")
    response = client.get("/dbs")
    assert response.status_code == 200


def test_read_only_allows_compare_post(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "1")
    response = client.post("/compare", json={"selections": []})
    assert response.status_code != 403


def test_read_only_blocks_trigger_run(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "1")
    db_id = client.get("/dbs").json()[0]["db_id"]
    response = client.post(f"/dbs/{db_id}/runs", json={"config": {"name": "x"}})
    assert response.status_code == 403
    assert response.json()["detail"] == "Hosted demo is read-only"


def test_read_only_off_does_not_403_runs_for_readonly_reason(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, None)
    db_id = client.get("/dbs").json()[0]["db_id"]
    response = client.post(f"/dbs/{db_id}/runs", json={"config": {"name": "x"}})
    assert response.status_code != 403
```

- [ ] **Step 2: Run tests — they must fail**

```bash
python -m pytest tests/unit/test_dashboard_read_only.py -v
```

Expected: FAIL because nothing returns 403 `"Hosted demo is read-only"` yet.

- [ ] **Step 3: Implement the guard in `create_app`**

Immediately after `app = FastAPI(...)` and the CORS middleware block, add:

```python
    _read_only = os.environ.get("RETOBS_READ_ONLY", "").strip().lower() in {"1", "true", "yes"}
    if _read_only:
        enable_uploads = False

    _READ_ONLY_POST_ALLOW = frozenset({"/compare", "/compare/config-diff"})

    if _read_only:
        from starlette.responses import JSONResponse

        @app.middleware("http")
        async def _hosted_demo_read_only(request, call_next):
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                path = request.url.path.rstrip("/") or "/"
                if path not in _READ_ONLY_POST_ALLOW:
                    return JSONResponse({"detail": "Hosted demo is read-only"}, status_code=403)
            return await call_next(request)
```

Keep this inside `create_app`. Do not import Azure. Do not change default local behavior when the env var is unset.

- [ ] **Step 4: Run tests — they must pass**

```bash
python -m pytest tests/unit/test_dashboard_read_only.py -v
```

Expected: PASS.

If `test_read_only_allows_compare_post` fails because empty `selections` is 422, that is fine as long as it is **not** 403. The assertion is `!= 403`.

If `test_read_only_off_does_not_403_runs_for_readonly_reason` hits 422/500 because the config is fake, that is fine as long as it is **not** 403.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_dashboard_read_only.py retrieval_observatory/dashboard/api.py
git commit -m "$(cat <<'EOF'
Block hosted-demo writes when RETOBS_READ_ONLY is set.

EOF
)"
```

---

### Task 5: Build the deploy image locally and open the dashboard

**Files:** none (run only)

**Interfaces:**
- Consumes: `deploy/Dockerfile`, `deploy/data/*.db`, Task 4 env behavior
- Produces: `retobs:demo` image; proof the BEIR runs appear

- [ ] **Step 1: Build**

```bash
docker build -f deploy/Dockerfile -t retobs:demo .
```

Expected: exit 0.

- [ ] **Step 2: Record image size**

```bash
docker image inspect retobs:demo --format '{{.Size}}'
```

Convert bytes to GB. If **> 2e9**, remove Cohere from the Dockerfile and rebuild. Write the chosen set and the size into notes for Task 8.

- [ ] **Step 3: Run**

```bash
docker run --rm -p 8000:8000 --name retobs-demo retobs:demo
```

Expected log: `Dashboard: http://localhost:8000` and **no** “Database not found”.

- [ ] **Step 4: Confirm three databases**

```bash
curl -sS http://127.0.0.1:8000/dbs
```

Expected: JSON array with **three** sources (nfcorpus, scifact, fiqa). Names follow `DbRegistry` id rules (usually the file stem).

- [ ] **Step 5: Confirm a known BEIR run is listed**

```bash
curl -sS http://127.0.0.1:8000/dbs
```

Pick the `db_id` for nfcorpus, then:

```bash
curl -sS "http://127.0.0.1:8000/dbs/<nfcorpus-db-id>/runs"
```

Expected: a run whose id is `37d3a79c` (see `results/RESULTS_OVERVIEW.md`). SciFact `49b423cf`, FiQA `0784ed30`.

- [ ] **Step 6: Confirm writes are rejected**

```bash
curl -sS -o /tmp/ro.json -w "%{http_code}\n" \
  -X POST "http://127.0.0.1:8000/dbs/<nfcorpus-db-id>/runs" \
  -H "Content-Type: application/json" \
  -d '{"config":{"name":"nope"}}'
```

Expected: `403` and `Hosted demo is read-only`.

- [ ] **Step 7: Open the UI in a browser**

Visit `http://127.0.0.1:8000`. Select the NFCorpus DB. Confirm run `37d3a79c` and pipeline metrics render. Stop the container.

---

### Task 6: Push the image to GHCR

**Files:** none in the app package

**Interfaces:**
- Consumes: `retobs:demo`
- Produces: public `ghcr.io/ameyaki/retrieval-observatory:demo`

- [ ] **Step 1: Log in to GHCR**

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u AmeyaKI --password-stdin
```

Use a GitHub PAT or `gh auth token` with `write:packages`. Do not put the token in the repo.

- [ ] **Step 2: Tag and push**

```bash
docker tag retobs:demo ghcr.io/ameyaki/retrieval-observatory:demo
docker push ghcr.io/ameyaki/retrieval-observatory:demo
```

Expected: push completes.

- [ ] **Step 3: Make the package public**

GitHub → Packages → `retrieval-observatory` → Package settings → Change visibility → Public.

This lets Azure pull **without** registry secrets. If you keep it private you must add GHCR credentials to Container Apps — more secrets, more failure modes. Prefer public.

---

### Task 7: Deploy Azure Container Apps

**Files:** none in the package. Use Azure CLI only.

**Interfaces:**
- Consumes: public GHCR image
- Produces: HTTPS URL

Resource names (use these unless they collide):

- Resource group: `rg-retobs-demo`
- Region: `eastus`
- Log analytics + ACA environment: `retobs-demo-env`
- App: `retobs-demo`

- [ ] **Step 1: Sign in and pick the subscription that has free credits**

```bash
az login
az account show --output table
az account set --subscription "<subscription-id>"
```

- [ ] **Step 2: Create the resource group**

```bash
az group create --name rg-retobs-demo --location eastus
```

Expected: `"provisioningState": "Succeeded"`.

- [ ] **Step 3: Create the Container Apps environment**

```bash
az containerapp env create \
  --name retobs-demo-env \
  --resource-group rg-retobs-demo \
  --location eastus
```

Expected: succeeded. If this command is the thing that fails (quota, policy, missing provider), **stop**. Try App Service for Containers next (same image, `az webapp create --deployment-container-image-name ...`). If Azure as a whole is blocked, switch to AWS App Runner with the same image. Do not keep retrying ACA with extra complexity.

- [ ] **Step 4: Create the app**

```bash
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
```

`--min-replicas 0` is what keeps idle cost near zero. First request after idle will be slow (cold start). That is acceptable for a resume demo.

- [ ] **Step 5: Print the URL**

```bash
az containerapp show \
  --name retobs-demo \
  --resource-group rg-retobs-demo \
  --query properties.configuration.ingress.fqdn \
  --output tsv
```

Expected: something like `retobs-demo.<random>.eastus.azurecontainerapps.io`.

- [ ] **Step 6: Confirm from the public internet**

```bash
FQDN="$(az containerapp show -n retobs-demo -g rg-retobs-demo --query properties.configuration.ingress.fqdn -o tsv)"
curl -sS -o /tmp/cloud-dbs.json -w "%{http_code}\n" "https://${FQDN}/dbs"
curl -sS -o /tmp/cloud-ro.json -w "%{http_code}\n" \
  -X POST "https://${FQDN}/dbs/<nfcorpus-db-id>/runs" \
  -H "Content-Type: application/json" \
  -d '{"config":{"name":"nope"}}'
```

Expected: GET `200` with three DBs; POST `403`.

- [ ] **Step 7: Browser check**

Open `https://<fqdn>` the way a recruiter would: land on the dashboard, pick NFCorpus, open run `37d3a79c`, confirm metrics. Cold start can take a minute. If it never loads, check:

```bash
az containerapp logs show -n retobs-demo -g rg-retobs-demo --follow
```

---

### Task 8: Write `docs/deployment.md` while the commands are still true

**Files:**
- Create: `docs/deployment.md`

**Interfaces:**
- Consumes: the exact commands that worked in Tasks 5–7
- Produces: a reader can redeploy from scratch

- [ ] **Step 1: Write the file with this structure and fill in the real FQDN, image size, and DB list**

```markdown
# Hosted demo deployment

RetObs stays local-first. This page is the **optional** path that publishes a
read-only dashboard of the committed BEIR sweep.

Live URL: https://<fqdn>

## What is hosted

- Image: `ghcr.io/ameyaki/retrieval-observatory:demo`
- Platform: Azure Container Apps, resource group `rg-retobs-demo`
- Data: SQLite copies of the BEIR publish sweep, **baked into the image**
  (nfcorpus `37d3a79c`, scifact `49b423cf`, fiqa `0784ed30`).
- Image size at last build: <size>
- Why bake, not mount: static demo; no extra storage account; dashboard
  requires SQLite, not the JSON under `results/`.

The published PyPI package is unchanged. There is no Azure SDK dependency.

## Prerequisites

- Docker
- Azure CLI (`az`)
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

## Deploy (Azure Container Apps)

```bash
az group create --name rg-retobs-demo --location eastus
az containerapp env create --name retobs-demo-env --resource-group rg-retobs-demo --location eastus
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
```

Required env vars (names only):

- `RETOBS_READ_ONLY` — set to `1` on the host
- `RETOBS_DASHBOARD_DBS` — already set in `deploy/Dockerfile`

No connection strings. No API keys.

## Cost

- Idle: scale to zero. Expect **$0** compute when nobody hits the URL.
- Cold start on first request after idle.
- Environment + Log Analytics may incur a small residual. Check:

```bash
az consumption usage list --start-date <today-30> --end-date <today>
```

Stay on the free / student / trial credit subscription. If monthly spend
is not ~$0, scale the app to zero replicas and delete the group (below).

## Teardown

```bash
az containerapp delete --name retobs-demo --resource-group rg-retobs-demo --yes
az containerapp env delete --name retobs-demo-env --resource-group rg-retobs-demo --yes
az group delete --name rg-retobs-demo --yes
```

Deleting the resource group removes the app, environment, and logs.

The GHCR image remains until you delete the GitHub package. It does not
bill Azure.

## Local-first (unchanged)

```bash
docker compose up
# or
retobs serve --db .retobs/results.db
```
```

Replace `<fqdn>` and `<size>` with the real values. Do not invent a URL.

- [ ] **Step 2: Commit**

```bash
git add docs/deployment.md
git commit -m "$(cat <<'EOF'
Document the optional Azure hosted-demo path.

EOF
)"
```

---

### Task 9: README link, changelog, local-first wording

**Files:**
- Modify: `README.md` (top, above Install)
- Modify: `CHANGELOG.md` under `[Unreleased]`

**Interfaces:**
- Consumes: live URL from Task 7
- Produces: recruiter-visible link; changelog lines

- [ ] **Step 1: Add the demo line at the very top of `README.md`**

After the title `# retobs` and the PyPI badge line, add:

```markdown
**Live demo (read-only BEIR dashboard):** https://<fqdn>

Local-first is still the default. The hosted URL serves pre-computed artifacts only. See [deployment](docs/deployment.md).
```

Do not move or rewrite the local `retobs demo` section. Do not present cloud as the primary install path.

- [ ] **Step 2: Changelog**

Under `[Unreleased]` → `Added`:

```markdown
- `docs/deployment.md` — optional Azure Container Apps URL for a read-only BEIR dashboard; image baked from local SQLite, no core-package cloud deps.
- `dashboard/api.py` — `RETOBS_READ_ONLY` returns 403 on mutating writes; `POST /compare` and `POST /compare/config-diff` stay allowed.
```

- [ ] **Step 3: Confirm `pyproject.toml` dependencies were not edited**

```bash
git diff main -- pyproject.toml
```

Expected: empty (or only unrelated pre-existing noise). If you touched dependencies, revert them.

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "$(cat <<'EOF'
Link the hosted demo from the README.

EOF
)"
```

---

### Task 10: Acceptance gate

**Files:** none

- [ ] **Step 1: Full test suite**

```bash
python -m pytest
```

Expected: green.

- [ ] **Step 2: Local compose still works**

```bash
docker compose up --build -d
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/dbs
docker compose down
```

Expected: `200`.

- [ ] **Step 3: `pip` extra list unchanged**

```bash
git diff HEAD -- pyproject.toml
```

Expected: no dependency changes.

- [ ] **Step 4: Secrets scan of what you will push**

```bash
git grep -nE 'sk-|DefaultEndpointsProtocol|AccountKey=|CLIENT_SECRET|ghp_' -- ':!SESSION_FLAGSHIP_DEMO.md' || true
```

Expected: no live credentials. The deployment doc names env vars only.

- [ ] **Step 5: Tick the brief’s acceptance box mentally**

- Public URL loads dashboard + BEIR results
- `docs/deployment.md` can redeploy from scratch
- README links the demo above the fold
- Core pip deps unchanged
- Local compose works
- Tests green
- No secrets committed; teardown documented
- Cost is scale-to-zero / credits; documented

---

## Fallback (only if Task 7 Step 3/4 fails)

1. **App Service for Containers** with the same `ghcr.io/...:demo` image and port 8000. Record why ACA failed in `docs/deployment.md`.
2. **AWS App Runner** with the same image. Record why Azure failed. Resume token becomes `AWS` instead of `Azure`. Either is success for the brief.

Do not add Terraform, Bicep, `azd`, or a cloud extra to `pyproject.toml` to “make it more official.”

---

## What we are not doing

- Live `retobs evaluate` on the host
- Auth, users, multi-tenancy
- Committing `.db` files
- Changing default `retobs serve` bind address
- Version bump / PyPI publish
- Rewriting the product as “RetObs Cloud”
