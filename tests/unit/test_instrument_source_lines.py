"""Decorators land on the right line when a string literal holds characters ``str.splitlines`` splits on."""
from __future__ import annotations

import ast

from retrieval_observatory.datasets.records import read_json_records
from retrieval_observatory.integrations.model import OperatorMapping
from retrieval_observatory.integrations.planner import _instrument_source


def _instrument(source: str) -> str:
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "search")
    operator = OperatorMapping("search", "SOURCE", "search", "app/search.py")
    return _instrument_source(source, [(node, operator)])


def test_separators_inside_a_string_literal_do_not_shift_decorators() -> None:
    source = (
        "import re\n"
        "\n"
        '_CONTROL = re.compile("[  \x0c\x1c\x85]")\n'
        "\n"
        "\n"
        "def search(query):\n"
        "    return []\n"
    )

    instrumented = _instrument(source)

    ast.parse(instrumented)
    lines = instrumented.split("\n")
    decorator = next(index for index, line in enumerate(lines) if line.startswith("@observe("))
    assert lines[decorator + 1] == "def search(query):"
    assert '"[  \x0c\x1c\x85]"' in instrumented


def test_crlf_source_keeps_its_line_endings() -> None:
    source = "import re\r\n\r\ndef search(query):\r\n    return []\r\n"

    instrumented = _instrument(source)

    ast.parse(instrumented)
    assert "def search(query):\r\n" in instrumented
    assert instrumented.index("@observe(") < instrumented.index("def search(query):")


def test_jsonl_record_holding_a_line_separator_is_one_record(tmp_path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        '{"id": "d1", "text": "first second"}\n{"id": "d2", "text": "third"}\n', encoding="utf-8"
    )

    assert read_json_records(corpus) == [
        {"id": "d1", "text": "first second"},
        {"id": "d2", "text": "third"},
    ]
