"""Three small project shapes an agent is expected to wire retobs into.

Copies of the reviewer's scratch projects, kept as file templates (not as importable packages)
so pytest never collects the fixture's own ``tests/`` directory and each test gets a pristine
copy under ``tmp_path``.

- ``proj_a``: plain Python, a module-level ``retrieve(query, k)`` plus a test file that must not
  be instrumented.
- ``proj_b``: FastAPI route handler delegating to class methods ``Searcher.search`` (SOURCE) and
  ``Searcher.rerank`` (RERANK); ``retobs_eval.py`` is the evaluate target.
- ``proj_c``: a LangChain ``BaseRetriever`` subclass whose ``_get_relevant_documents`` is the
  operator; ``build_retriever`` is a name-only hit that must stay out of the plan.
"""
from __future__ import annotations

from pathlib import Path

CORPUS_JSONL = """{"id": "d1", "text": "Retrieval observatory benchmarks hybrid RAG pipelines."}
{"id": "d2", "text": "BM25 is a lexical sparse retriever based on term frequency."}
{"id": "d3", "text": "Dense embeddings capture semantic similarity between queries and documents."}
{"id": "d4", "text": "Reranking improves precision by applying a cross-encoder to candidates."}
{"id": "d5", "text": "RAG systems ground language model responses in retrieved documents."}
{"id": "d6", "text": "Postgres pgvector stores embeddings for approximate nearest neighbour search."}
"""

QUERIES_JSONL = """{"query_id": "q1", "text": "lexical sparse retriever term frequency"}
{"query_id": "q2", "text": "dense embeddings semantic similarity"}
{"query_id": "q3", "text": "cross-encoder reranking precision"}
{"query_id": "q4", "text": "pgvector nearest neighbour"}
"""

QRELS_LIST_JSONL = """{"query_id": "q1", "relevant_doc_ids": ["d2"]}
{"query_id": "q2", "relevant_doc_ids": ["d3"]}
{"query_id": "q3", "relevant_doc_ids": ["d4"]}
{"query_id": "q4", "relevant_doc_ids": ["d6"]}
"""

QRELS_ROW_JSONL = """{"query_id": "q1", "doc_id": "d2", "relevance": 1}
{"query_id": "q2", "doc_id": "d3", "relevance": 1}
{"query_id": "q3", "doc_id": "d4", "relevance": 1}
{"query_id": "q4", "doc_id": "d6", "relevance": 1}
"""

DATA_FILES = {
    "data/corpus.jsonl": CORPUS_JSONL,
    "data/queries.jsonl": QUERIES_JSONL,
    "data/qrels.jsonl": QRELS_LIST_JSONL,
    "data/qrels_rows.jsonl": QRELS_ROW_JSONL,
}

_CORPUS_PY = '''CORPUS = {
    "d1": "Retrieval observatory benchmarks hybrid RAG pipelines.",
    "d2": "BM25 is a lexical sparse retriever based on term frequency.",
    "d3": "Dense embeddings capture semantic similarity between queries and documents.",
    "d4": "Reranking improves precision by applying a cross-encoder to candidates.",
    "d5": "RAG systems ground language model responses in retrieved documents.",
    "d6": "Postgres pgvector stores embeddings for approximate nearest neighbour search.",
}
'''

PROJ_A = {
    "README.md": "# proj_a\n",
    "search/__init__.py": "",
    "search/retriever.py": (
        '"""Tiny lexical retriever over an in-memory corpus."""\n'
        "from __future__ import annotations\n\n"
        "import re\n\n"
        + _CORPUS_PY.replace("CORPUS = {", "CORPUS: dict[str, str] = {")
        + "\n\n"
        "def _tokenize(text: str) -> list[str]:\n"
        '    return re.findall(r"[a-z0-9]+", text.lower())\n\n\n'
        "def _score(query_tokens: list[str], doc_tokens: list[str]) -> float:\n"
        "    return float(sum(1 for t in query_tokens if t in doc_tokens))\n\n\n"
        "def retrieve(query: str, k: int = 10) -> list[dict]:\n"
        "    q = _tokenize(query)\n"
        "    scored = [\n"
        '        {"id": doc_id, "score": _score(q, _tokenize(text)), "text": text}\n'
        "        for doc_id, text in CORPUS.items()\n"
        "    ]\n"
        '    scored.sort(key=lambda d: d["score"], reverse=True)\n'
        "    return scored[:k]\n"
    ),
    "tests/test_retriever.py": (
        "from search.retriever import retrieve\n\n\n"
        "def test_retrieve_returns_k():\n"
        '    assert len(retrieve("lexical", k=2)) == 2\n'
    ),
    **DATA_FILES,
}

PROJ_B = {
    "app/__init__.py": "",
    "app/searcher.py": (
        "from __future__ import annotations\n\n"
        "import re\n\n"
        + _CORPUS_PY
        + "\n\n"
        "class Searcher:\n"
        "    def __init__(self, corpus: dict[str, str] | None = None):\n"
        "        self.corpus = corpus or CORPUS\n\n"
        "    def _tokens(self, text: str) -> set[str]:\n"
        '        return set(re.findall(r"[a-z0-9]+", text.lower()))\n\n'
        "    def search(self, q: str, k: int = 20) -> list[dict]:\n"
        "        qt = self._tokens(q)\n"
        '        hits = [{"id": i, "score": float(len(qt & self._tokens(t))), "text": t} for i, t in self.corpus.items()]\n'
        '        hits.sort(key=lambda h: h["score"], reverse=True)\n'
        "        return hits[:k]\n\n"
        "    def rerank(self, q: str, hits: list[dict], k: int = 5) -> list[dict]:\n"
        '        # crude "cross-encoder": bonus for exact phrase match\n'
        "        for h in hits:\n"
        '            h["score"] += 1.0 if q.lower() in h["text"].lower() else 0.0\n'
        '        return sorted(hits, key=lambda h: h["score"], reverse=True)[:k]\n'
    ),
    "app/main.py": (
        "from fastapi import FastAPI\n"
        "from pydantic import BaseModel\n\n"
        "from app.searcher import Searcher\n\n"
        "app = FastAPI()\n"
        "searcher = Searcher()\n\n\n"
        "class SearchRequest(BaseModel):\n"
        "    q: str\n"
        "    k: int = 5\n\n\n"
        '@app.post("/search")\n'
        "def search(body: SearchRequest) -> list[dict]:\n"
        "    hits = searcher.search(body.q, k=20)\n"
        "    return searcher.rerank(body.q, hits, k=body.k)\n\n\n"
        '@app.get("/health")\n'
        "def health() -> dict:\n"
        '    return {"ok": True}\n'
    ),
    **DATA_FILES,
}

#: The evaluate target the reviewer added to proj_b after apply (``retobs evaluate
#: retobs_eval.py:PIPELINE``); kept out of the plan so the scenario covers only live operators.
PROJ_B_EVAL_TARGET = (
    "from app.searcher import Searcher\n"
    "_s = Searcher()\n"
    "def retrieve(q: str):\n"
    "    return _s.search(q, k=20)\n"
    "def rerank(q: str, docs):\n"
    '    hits = [{"id": d.id, "score": d.score, "text": d.text} for d in docs]\n'
    "    return _s.rerank(q, hits, k=5)\n"
    "PIPELINE = [retrieve, rerank]\n"
)

PROJ_C = {
    "rag/__init__.py": "",
    "rag/retriever.py": (
        "from __future__ import annotations\n\n"
        "from typing import List\n\n"
        "from langchain_core.callbacks import CallbackManagerForRetrieverRun\n"
        "from langchain_core.documents import Document\n"
        "from langchain_core.retrievers import BaseRetriever\n\n"
        + _CORPUS_PY
        + "\n\n"
        "class KeywordRetriever(BaseRetriever):\n"
        "    k: int = 4\n\n"
        "    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> List[Document]:\n"
        "        qt = set(query.lower().split())\n"
        "        scored = sorted(\n"
        "            CORPUS.items(),\n"
        "            key=lambda kv: -len(qt & set(kv[1].lower().split())),\n"
        "        )\n"
        '        return [Document(page_content=t, metadata={"id": i}) for i, t in scored[: self.k]]\n\n\n'
        "def build_retriever(k: int = 4) -> KeywordRetriever:\n"
        "    return KeywordRetriever(k=k)\n"
    ),
    "rag/chain.py": (
        "from rag.retriever import build_retriever\n\n\n"
        "def answer(question: str) -> str:\n"
        "    docs = build_retriever().invoke(question)\n"
        '    return "\\n".join(d.page_content for d in docs)\n'
    ),
    "rag/eval_target.py": (
        "from rag.retriever import build_retriever\n"
        "retriever = build_retriever(k=4)\n"
    ),
    **DATA_FILES,
}

PROJECTS = {"proj_a": PROJ_A, "proj_b": PROJ_B, "proj_c": PROJ_C}


def materialize(name: str, destination: Path) -> Path:
    """Write project ``name`` under ``destination / name`` and return that root."""
    root = destination / name
    for relative, content in PROJECTS[name].items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root
