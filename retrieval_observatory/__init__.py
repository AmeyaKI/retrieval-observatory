from __future__ import annotations

from typing import Any, TypeAlias

from retrieval_observatory.forge.types import TestSetSummary as TestSet
from retrieval_observatory.integrations import IntegrationOptions
from retrieval_observatory.sdk import compare, evaluate, generate_testset, inspect_query
from retrieval_observatory.sdk.report import BenchmarkReport as Run
from retrieval_observatory.sdk.report import ReportModel as Comparison
from retrieval_observatory.tracing import RetrievalTrace, TraceRecorder, init
from retrieval_observatory.types import Document, Query

QueryEvidence: TypeAlias = dict[str, Any]

__all__ = [
    "Comparison",
    "Document",
    "IntegrationOptions",
    "Query",
    "QueryEvidence",
    "RetrievalTrace",
    "Run",
    "TestSet",
    "TraceRecorder",
    "compare",
    "evaluate",
    "generate_testset",
    "init",
    "inspect_query",
]
