from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
FIXTURES = ("python_callable", "fastapi_hybrid_dag", "langchain_retriever", "llamaindex_retriever")


@pytest.mark.parametrize("name", FIXTURES)
def test_external_fixture_is_self_contained(name: str) -> None:
    root = ROOT / name
    expected = json.loads((root / "expected.json").read_text(encoding="utf-8"))

    assert (root / "pyproject.toml").is_file()
    assert expected["required_operator_ids"]
    assert expected["scenario_ids"]
    assert (root / "data" / "corpus.jsonl").is_file()
    assert (root / "data" / "queries.jsonl").is_file()
    assert (root / "data" / "qrels.jsonl").is_file()

    source = "\n".join(path.read_text(encoding="utf-8") for path in (root / "app").rglob("*.py"))
    assert "retrieval_observatory" not in source
    assert "sys.path" not in source
