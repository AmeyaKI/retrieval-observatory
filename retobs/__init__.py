"""retobs — public import path for the retrieval reliability platform.

Install: ``pip install retobs``
Import:  ``import retobs as ro``
"""

from retrieval_observatory.types import StageSnapshot  # noqa: F401
from retrieval_observatory import (  # noqa: F401
    EXAMPLES_DIR,
    PACKAGE_DIR,
    BenchmarkReport,
    Document,
    FunctionReranker,
    FunctionRetriever,
    Query,
    as_retriever,
    benchmark,
    generate_testset,
    reranker,
    retriever,
)

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
    "StageSnapshot",
]
