# Contributing to Retrieval Observatory

Thanks for helping improve retobs. This guide covers local setup, tests, and conventions.

## Development setup

```bash
git clone https://github.com/<your-fork>/retrieval-observatory
cd retrieval-observatory
pip install -e ".[demo,dashboard,dense,mcp]"
```

Verify your install:

```bash
retobs doctor
```

## Running the tests

The Python test suite is the source of truth for backend correctness:

```bash
pytest -q
```

Run a focused subset while iterating, e.g.:

```bash
pytest tests/unit/test_attribution_segments.py -v
```

## Building the dashboard UI

The dashboard is a Vite + React + TypeScript SPA under
`retrieval_observatory/dashboard/ui/`:

```bash
cd retrieval_observatory/dashboard/ui
npm install
npm run build      # tsc + vite build; must pass with no type errors
npm run dev        # local dev server
```

A UI change is not done until `npm run build` is clean.

## Conventions

- **Correctness over cleverness.** retobs's value is that its numbers are trustworthy. Never
  fabricate a metric, attribution, or topology when it can't be determined — surface the
  uncertainty instead (`None`, "not estimated", "inferred", `NOT_REPLAYABLE`). New features
  should preserve this.
- **Trace-native.** Topology and attribution come from real execution traces
  (`RetrievalTraceV2`), not heuristics, whenever traces exist.
- **Tests with behavior.** Backend changes land with unit tests that assert the actual
  behavior, including the uncertain/edge cases.
- **Small, reviewable commits**, each leaving the suite green.

## Pull requests

1. Branch from `main`.
2. Keep the diff focused; note any deviations from the plan in the PR description.
3. Confirm `pytest -q` and (for UI changes) `npm run build` both pass.
4. Describe what you verified, not just what you changed.

## Reporting issues

Include: retobs version, how you ran it (CLI/SDK/dashboard), the config or dataset shape, and
what you expected vs. observed. For diagnostic questions, the run manifest (dataset
fingerprint, seed, versions) makes issues reproducible.
