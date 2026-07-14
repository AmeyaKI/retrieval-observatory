# Contributing to retobs

## Setup

```bash
git clone https://github.com/AmeyaKI/retrieval-observatory
cd retrieval-observatory
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,dashboard,demo,dense,mcp]"
npm ci --prefix retrieval_observatory/dashboard/ui
```

## CI parity

Run these before opening a pull request:

```bash
.venv/bin/ruff check retrieval_observatory tests scripts
.venv/bin/pytest tests/unit -v --tb=short
.venv/bin/pytest tests/integration -v --tb=short -m "not slow"
npm run test --prefix retrieval_observatory/dashboard/ui
npm run build --prefix retrieval_observatory/dashboard/ui
.venv/bin/python scripts/check_markdown_links.py
```

Browser tests require Chromium and a running deterministic demo:

```bash
.venv/bin/retobs demo --db .retobs/e2e/results.db --output-dir .retobs/e2e --n-traces 80
.venv/bin/retobs serve --host 127.0.0.1 --port 4000 --db .retobs/e2e/results.db
RETOBS_E2E_URL=http://127.0.0.1:4000 .venv/bin/pytest tests/browser -v
```

PostgreSQL parity requires `RETOBS_POSTGRES_DSN` and runs `tests/unit/test_store_postgres.py`.

## Engineering rules

- Preserve uncertainty: unsupported evidence is `None`/unavailable, never fabricated precision.
- Derive topology and attribution from V2 traces and recorded candidate transitions.
- Keep database/Run/query scope explicit.
- Add behavior tests for success, partial, and failure paths.
- Update `[Unreleased]` in `CHANGELOG.md` for user-visible behavior.
- Keep changes focused and retain read compatibility when removing a public surface.

## Pull requests and issues

Describe the user-visible delta, evidence/compatibility impact, and exact verification commands. Include a Run manifest for reproducibility, but redact sensitive query/document data. Use the issue templates for bugs and features, the [security policy](SECURITY.md) for vulnerabilities, and the [Code of Conduct](CODE_OF_CONDUCT.md) for participation expectations.
