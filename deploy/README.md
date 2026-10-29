# Hosted demo: read-only dashboard on Azure Container Apps

The public URL serves the retobs dashboard over three baked SQLite databases: a real SciFact
run (`scifact`, the one the site opens on), the built-in demo (`demo`, for compare and Audit), and
a verified integration (`integration`, for Connect). Nothing on the instance is writable. This file is the
operational record: what a maintainer runs, what was checked before exposure, and the results.

## What a maintainer runs

Two authenticated steps. Everything else is scripted or automated.

1. **Make the image public, once.** The `Demo image` workflow (`.github/workflows/demo-image.yml`)
   builds `deploy/Dockerfile` and pushes `ghcr.io/ameyaki/retrieval-observatory:demo` on every
   push to `main` that touches the app or `deploy/`, and on manual dispatch. After the first run,
   open the package on GitHub → Package settings → Change visibility → Public, so Azure can pull
   without registry credentials.
2. **Deploy.**

   ```bash
   az login
   ./deploy/deploy_azure.sh
   ```

   The script creates the resource group, the Container Apps environment, and the app (or
   updates the image if the app exists, with a new revision suffix so Azure pulls the
   re-pushed `:demo` tag), then polls `/healthz` until it returns `"read_only": true` and prints
   the URL. Re-run it after every image rebuild to roll forward; to pin a build, set
   `RETOBS_DEMO_IMAGE=ghcr.io/ameyaki/retrieval-observatory:demo-<commit sha>`.

Then paste the URL into the `Hosted demo` line at the top of `README.md` and into
`docs/deployment.md`.

## Health check

```bash
curl -fsS "https://<fqdn>/healthz"
# {"status":"ok","read_only":true,"databases":3}
curl -fsS "https://<fqdn>/dbs"
# scifact, demo, integration; "path" is a basename, never a container path
```

## Rebuilding the data

The container opens every database with SQLite `mode=ro`, so each one must be complete before
the image is built. `deploy/prepare_data.py` copies each source, migrates it once writable,
rewrites absolute build paths to relative ones, indexes every run for Investigate, refuses the
database if any absolute path or e-mail address is left, proves it opens read-only, and writes it
gzip-compressed to `deploy/data/<name>.db.gz`. The Dockerfile unpacks them into `/data/` and
marks them `chmod 444`. The baked files are committed so CI can build the image without local
state. No step needs a network: the SciFact data and the small vector model come from local caches.

```bash
DIR=/tmp/retobs-hosted
python tests/browser/seed_e2e.py "$DIR"                 # built-in demo + a verified integration, model-free
HF_HUB_OFFLINE=1 retobs evaluate --config deploy/scifact_hybrid.yaml --db "$DIR/scifact.db"   # about 20 s
python deploy/prepare_data.py scifact="$DIR/scifact.db" demo="$DIR/demo/demo.db" \
  integration="$DIR/project/.retobs/results.db" --relative-to "$DIR/project" --relative-to "$DIR"
git add deploy/data && git commit -m "deploy: rebake demo data"
```

The SciFact run needs the BEIR SciFact files and `sentence-transformers/all-MiniLM-L6-v2`
cached locally; drop `HF_HUB_OFFLINE=1` once to fetch the model (about 90 MB). A pull request
that changes `deploy/` builds the image and checks that every baked run opens in Investigate.

## Public-exposure checklist (run 2026-09-10 against the baked databases)

Every item was exercised with the app configured exactly as the container runs it
(`RETOBS_READ_ONLY=1`, three `chmod 444` databases, read-only registry). Automated
coverage lives in `tests/unit/test_dashboard_read_only.py`.

| # | Check | Result |
| --- | --- | --- |
| 1 | Every mutating method (POST/PUT/PATCH/DELETE) returns 403 except `POST /compare` and `POST /compare/config-diff`, which only read run manifests and metrics | PASS: trace ingest, edges, run trigger, uploads, PUT and DELETE all 403; compare 200 |
| 2 | Database files are opened read-only | PASS: `SQLiteStore(read_only=True)` opens `file:…?mode=ro`; a write raises `attempt to write a readonly database`; files are also `chmod 444` and the process runs as a non-root user |
| 3 | The read-only store never runs DDL; an incomplete schema is a startup error, not a silent write | PASS: `init_db` checks `sqlite_master` and names the missing tables. The pre-bake files were missing 18 tables, which the previous image created by writing to them at startup |
| 4 | No route accepts a filesystem path, database path, or SQL fragment | PASS: databases are addressed by registry id only; the one path-typed input (`policy_path` on compare and lineage-diff) returns 403 in read-only mode; SQL uses bound parameters with fixed column names |
| 5 | Every query parameter is validated | PASS: ints and bools are type-checked by FastAPI; `limit`, `offset`, `k` are bounded (422 outside range); `since`, `until`, `baseline`, `recent` must parse as ISO-8601 (422, previously 500) |
| 6 | Static assets cannot escape their directory; unknown paths get the SPA index, not files | PASS: raw ASGI requests for `/assets/../../../../etc/passwd` and the URL-encoded form return 404; `/etc/passwd` returns `index.html` |
| 7 | Per-IP rate limiting | PASS: 300 requests per minute per client, keyed on the first `X-Forwarded-For` hop set by the Azure ingress; 429 with `Retry-After`. Azure Container Apps has no free-tier request throttling, so this is middleware |
| 8 | Image contains no `.env`, credentials, or non-demo data | PASS: `.dockerignore` excludes `.env`, `.retobs/`, `results/`, `dist/`, `artifacts/`, `*.jsonl`, `*.png`, `.git`; the only data copied in is `deploy/data/*.db.gz` (2026-10-25: also baked with no absolute path or e-mail left, enforced by `prepare_data.py`) |
| 9 | `/dbs` does not reveal container filesystem paths | PASS: basenames only in read-only mode |
| 10 | Local behaviour unchanged | PASS: with `RETOBS_READ_ONLY` unset the store opens writable, no rate limit, no 403s; full suite green |

Known and accepted: the OpenAPI schema at `/openapi.json` and `/docs` stays public (read-only
routes only), and CORS allows any origin (nothing is writable and nothing is authenticated).

## Cost and teardown

Scale-to-zero (`--min-replicas 0`) means no compute charge while idle; the first request after
idle pays a cold start. Log Analytics may show a small residual. A free-tier or trial credit
subscription is sufficient.

```bash
az group delete --name rg-retobs-demo --yes     # removes app, environment, and logs
```

The GHCR image is not billed by Azure and stays until the GitHub package is deleted.

## If Azure blocks

Same image, same port: **Azure App Service for Containers**, or **AWS App Runner** if the
subscription cannot create Container Apps at all. Record what actually worked here and in
`docs/deployment.md`, and make sure the provider named in the docs is the one actually in use.
