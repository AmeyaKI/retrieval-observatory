from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
EXAMPLES_DIR = PACKAGE_DIR / "examples"

from retrieval_observatory.sdk import (  # noqa: E402
    BenchmarkReport,
    FunctionReranker,
    FunctionRetriever,
    as_retriever,
    benchmark,
    compare,
    evaluate,
    fuse,
    generate_testset,
    inspect_query,
    reranker,
    retriever,
    run_from_config,
)
from retrieval_observatory.types import Document, Query, StageSnapshot  # noqa: E402


def init(*args, **kwargs):
    """One-line production tracing setup. See ``retrieval_observatory.tracing.init``."""
    from retrieval_observatory.tracing import init as _init

    return _init(*args, **kwargs)


__all__ = [
    "EXAMPLES_DIR",
    "PACKAGE_DIR",
    "benchmark",
    "compare",
    "evaluate",
    "run_from_config",
    "fuse",
    "init",
    "generate_testset",
    "inspect_query",
    "retriever",
    "reranker",
    "as_retriever",
    "FunctionRetriever",
    "FunctionReranker",
    "BenchmarkReport",
    "Document",
    "Query",
    "StageSnapshot",
]
