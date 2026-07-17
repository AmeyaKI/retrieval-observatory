# Release checklist

Release proof is generated in `artifacts/release-evidence.json` and `artifacts/release-evidence.md`. A release is not ready when a gate is a manual checkbox, missing, skipped, failed, or tied to a different wheel digest.

Run the candidate workflow to build one wheel, test that exact wheel, collect every gate result, and generate the evidence artifact. Its final gate is:

```bash
python scripts/generate_release_evidence.py --results-dir results --dist dist --output-json artifacts/release-evidence.json --output-markdown artifacts/release-evidence.md
python scripts/check_release.py --require-assets --require-wheel dist/retrieval_observatory-*.whl --require-evidence artifacts/release-evidence.json
```

The generated report records the command, status, evidence artifact, wheel SHA-256, and timestamp for public-surface, vocabulary, link, Python, store, UI, browser, wheel, external-project, and digest gates. `check_release.py` also verifies the package, wheel metadata, installed-wheel runtime, generated demo assets, and release evidence all report the same version.

For a local candidate proof, run:

```bash
ruff check retrieval_observatory tests scripts
pytest tests/unit tests/contracts -v --tb=short
pytest tests/integration -v --tb=short
npm ci --prefix retrieval_observatory/dashboard/ui
npm run test --prefix retrieval_observatory/dashboard/ui -- --run
npm run build --prefix retrieval_observatory/dashboard/ui
python -m build
twine check dist/*
python scripts/smoke_external_project.py --wheel dist/retrieval_observatory-*.whl --fixture all --artifacts artifacts/external-fixtures
python scripts/check_release.py --require-assets --require-wheel dist/retrieval_observatory-*.whl --require-evidence artifacts/release-evidence.json
git diff --check
git status --short
```

Only these external governance actions remain manual confirmations:

- trusted-publisher environment approval;
- private vulnerability-disclosure review;
- release-note approval.
