#!/usr/bin/env python3
"""Generate a temporal retrieval demo dataset."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent

DOCS = [
    {"id": "policy_2021", "text": "Refund policy update 2021 allows refunds within 30 days.", "timestamp": "2021-01-10T00:00:00"},
    {"id": "policy_2024", "text": "Refund policy update 2024 allows refunds within 7 days.", "timestamp": "2024-01-10T00:00:00"},
    {"id": "release_2020", "text": "Product release notes 2020 include the classic dashboard.", "timestamp": "2020-06-01T00:00:00"},
    {"id": "release_2024", "text": "Product release notes 2024 include the new analytics dashboard.", "timestamp": "2024-05-15T00:00:00"},
    {"id": "pricing_2022", "text": "Pricing guide 2022 lists the pro plan at 49 dollars.", "timestamp": "2022-03-01T00:00:00"},
    {"id": "pricing_2025", "text": "Pricing guide 2025 lists the pro plan at 79 dollars.", "timestamp": "2025-02-01T00:00:00"},
    {"id": "security_2022", "text": "Security policy 2022 requires monthly key rotation.", "timestamp": "2022-08-01T00:00:00"},
    {"id": "security_2025", "text": "Security policy 2025 requires weekly key rotation.", "timestamp": "2025-01-15T00:00:00"},
    {"id": "billing_2020", "text": "Billing FAQ 2020 describes annual invoice process.", "timestamp": "2020-02-10T00:00:00"},
    {"id": "billing_2024", "text": "Billing FAQ 2024 describes self-serve invoice downloads.", "timestamp": "2024-07-10T00:00:00"},
    {"id": "oncall_2021", "text": "On-call runbook 2021 says escalation starts at severity one.", "timestamp": "2021-04-12T00:00:00"},
    {"id": "oncall_2024", "text": "On-call runbook 2024 adds severity two auto-paging.", "timestamp": "2024-11-05T00:00:00"},
    {"id": "api_2019", "text": "API limits 2019 cap requests at 100 per minute.", "timestamp": "2019-09-01T00:00:00"},
    {"id": "api_2024", "text": "API limits 2024 cap requests at 300 per minute.", "timestamp": "2024-09-01T00:00:00"},
    {"id": "retention_2022", "text": "Data retention policy 2022 keeps logs for 30 days.", "timestamp": "2022-01-01T00:00:00"},
    {"id": "retention_2025", "text": "Data retention policy 2025 keeps logs for 90 days.", "timestamp": "2025-03-01T00:00:00"},
    {"id": "support_2021", "text": "Support SLA 2021 target first response in 24 hours.", "timestamp": "2021-05-03T00:00:00"},
    {"id": "support_2024", "text": "Support SLA 2024 target first response in 4 hours.", "timestamp": "2024-10-03T00:00:00"},
    {"id": "ops_2020", "text": "Incident postmortem process 2020 emphasizes weekly review.", "timestamp": "2020-11-20T00:00:00"},
    {"id": "ops_2024", "text": "Incident postmortem process 2024 emphasizes 24 hour review.", "timestamp": "2024-12-20T00:00:00"},
]

QUERIES = [
    {"query_id": "q1", "text": "What is the latest refund policy update?", "temporal_anchor": "2024-02-01T00:00:00", "relevant_doc_ids": ["policy_2021", "policy_2024"]},
    {"query_id": "q2", "text": "Latest product release notes dashboard changes", "temporal_anchor": "2024-06-01T00:00:00", "relevant_doc_ids": ["release_2020", "release_2024"]},
    {"query_id": "q3", "text": "Current pro plan pricing guide", "temporal_anchor": "2025-02-15T00:00:00", "relevant_doc_ids": ["pricing_2022", "pricing_2025"]},
    {"query_id": "q4", "text": "Most recent security policy key rotation", "temporal_anchor": "2025-01-20T00:00:00", "relevant_doc_ids": ["security_2022", "security_2025"]},
    {"query_id": "q5", "text": "Current billing FAQ invoice downloads", "temporal_anchor": "2024-08-01T00:00:00", "relevant_doc_ids": ["billing_2020", "billing_2024"]},
    {"query_id": "q6", "text": "Latest on-call runbook severity escalation", "temporal_anchor": "2024-11-20T00:00:00", "relevant_doc_ids": ["oncall_2021", "oncall_2024"]},
    {"query_id": "q7", "text": "Current API limits requests per minute", "temporal_anchor": "2024-09-20T00:00:00", "relevant_doc_ids": ["api_2019", "api_2024"]},
    {"query_id": "q8", "text": "Newest data retention policy logs days", "temporal_anchor": "2025-03-20T00:00:00", "relevant_doc_ids": ["retention_2022", "retention_2025"]},
    {"query_id": "q9", "text": "Latest support SLA first response time", "temporal_anchor": "2024-10-20T00:00:00", "relevant_doc_ids": ["support_2021", "support_2024"]},
    {"query_id": "q10", "text": "Most recent incident postmortem process", "temporal_anchor": "2024-12-31T00:00:00", "relevant_doc_ids": ["ops_2020", "ops_2024"]},
]


def main() -> None:
    with (OUT / "corpus.jsonl").open("w") as f:
        for doc in DOCS:
            f.write(json.dumps(doc) + "\n")

    with (OUT / "queries.jsonl").open("w") as f:
        for q in QUERIES:
            f.write(json.dumps(q) + "\n")

    print(f"Wrote {len(DOCS)} docs and {len(QUERIES)} temporal queries to {OUT}")


if __name__ == "__main__":
    main()
