# Production trace views (retired)

The Production workspace, the `retobs production` subcommands, and the monitoring views built on
production traces (hotspots, drift, clusters, distributions, test-set origin lookup) were retired
in 0.7.0.

Traces your application records with `@trace_scope`, a framework callback, or `push_traces` are
still stored. To see where relevant documents were lost, evaluate the instrumented entrypoint on
judged queries and open the Run in Investigate: see
[investigate your pipeline](investigate-your-pipeline.md). Integration verification is described
in the [agent runbook](../integrations/AGENT_QUICKSTART.md).

What changed and what replaces it: [migrating to focused retobs](migrating-to-focused-retobs.md).
To reproduce the retired views, pin `retrieval-observatory==0.6.0` (repository revision
`29c67b8`).
