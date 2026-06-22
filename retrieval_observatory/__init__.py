from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
EXAMPLES_DIR = PACKAGE_DIR / "examples"

from retrieval_observatory.sdk import (  # noqa: E402
    BenchmarkReport,
    FunctionReranker,
    FunctionRetriever,
    as_retriever,
    benchmark,
    generate_testset,
    reranker,
    retriever,
)
from retrieval_observatory.types import Document, Query  # noqa: E402

__all__ = [
    "EXAMPLES_DIR",
    "PACKAGE_DIR",
    "benchmark",
    "generate_testset",
    "retriever",
    "reranker",
    "as_retriever",
    "FunctionRetriever",
    "FunctionReranker",
    "BenchmarkReport",
    "Document",
    "Query",
]
