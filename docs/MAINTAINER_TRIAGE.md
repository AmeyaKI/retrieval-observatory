# Maintainer triage

The target is an initial response within seven days for reproducible bugs and security reports. This is a best-effort alpha project, not a support SLA.

Priority order:

1. data corruption, cross-database evidence leakage, false causal/statistical claims, or security issues;
2. executor/trace/store contract regressions and broken callable/compare workflows;
3. first-class integration API drift;
4. accessibility, documentation, supported examples, and enhancements.

Good first issues should be bounded, require no product-contract invention, and name a verification command. Suitable seeds include adding a missing explicit unavailable-state fixture, extending Markdown link-check fixtures, improving one support-matrix example, and adding keyboard coverage for a single semantic control.
