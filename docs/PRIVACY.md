# Data and privacy

retobs is local-first: it does not require a hosted retobs service. SQLite/PostgreSQL data and generated reports stay where the user places them. This does not make every integration private automatically.

Potentially sensitive fields include query text, document IDs/content/metadata, filters, relevance judgments, candidate lists/scores, errors, service names, traces, and generated Test Set prompts/outputs. Before production use:

- choose sampling and retention deliberately;
- redact secrets and personal/customer data before recording metadata or errors;
- restrict filesystem/database access;
- do not expose the unauthenticated single-tenant dashboard to an untrusted network;
- review report artifacts before uploading them to CI or a pull request;
- configure deletion with `retobs production purge` and database retention controls.

Rule-based Test Set generation is local. Selecting an LLM generator or judge sends the supplied prompt/corpus excerpts to that provider under its policy and may incur cost. Generated or extractive qrels remain labeled with their method until human/judge validation is recorded.

Security issues should follow [SECURITY.md](../SECURITY.md).
