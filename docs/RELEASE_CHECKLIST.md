# Release checklist

- [ ] Version and tag match; `CHANGELOG.md` distinguishes Added/Changed/Fixed/Removed and preview limits.
- [ ] Python tests, PostgreSQL parity, Ruff, UI tests/build, browser/accessibility checks, and Markdown links pass.
- [ ] First-class framework jobs and supported-example jobs pass in their separate tiers.
- [ ] `retobs demo` completes regression → query cause → validation without contract warnings.
- [ ] `scripts/generate_demo_assets.py` was run against the release candidate and `scripts/check_release.py --require-assets` passes.
- [ ] Wheel metadata/UI/examples are present and `scripts/smoke_wheel.py` passes inside a clean wheel-only environment.
- [ ] Migration warnings name replacements/removal version; old fixture reads still pass.
- [ ] Security, privacy, contribution, issue templates, support levels, and maintainer triage guidance are current.
- [ ] PR Markdown and standalone HTML show validity, effects, q-values, paired `n`, affected queries, and no-decision reasons.
- [ ] Launch text calls Production/Test Sets preview where appropriate and does not imply heuristic replay is causal proof.
