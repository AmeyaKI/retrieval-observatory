from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from retrieval_observatory.integrations.model import CAPABILITY_NAMES

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from conftest import FIXTURES  # noqa: E402

OVERRIDE_KEYS = {"remove_operators", "operators", "scenarios", "entrypoint"}
OPERATOR_EDIT_KEYS = {"op_id", "op_type", "parent_ids", "capture"}
SCENARIO_KEYS = {"scenario_id", "query_text", "expected_operator_ids", "route", "command"}


@pytest.mark.parametrize("name", FIXTURES)
def test_external_fixture_is_self_contained(name: str) -> None:
    root = ROOT / name
    expected = json.loads((root / "expected.json").read_text(encoding="utf-8"))

    assert (root / "pyproject.toml").is_file()
    assert expected["required_operator_ids"]
    assert expected["scenario_ids"]
    assert expected["required_capabilities"] == list(CAPABILITY_NAMES)
    assert (root / "data" / "corpus.jsonl").is_file()
    assert (root / "data" / "queries.jsonl").is_file()
    assert (root / "data" / "qrels.jsonl").is_file()

    source = "\n".join(path.read_text(encoding="utf-8") for path in (root / "app").rglob("*.py"))
    assert "retrieval_observatory" not in source
    assert "sys.path" not in source


@pytest.mark.parametrize("name", FIXTURES)
def test_plan_overrides_are_well_formed(name: str) -> None:
    root = ROOT / name
    overrides = json.loads((root / "expected.json").read_text(encoding="utf-8")).get("plan_overrides")
    if overrides is None:
        return

    assert set(overrides) <= OVERRIDE_KEYS
    assert all(isinstance(op_id, str) for op_id in overrides.get("remove_operators", []))
    for planned_id, edit in overrides.get("operators", {}).items():
        assert isinstance(planned_id, str) and set(edit) <= OPERATOR_EDIT_KEYS, planned_id
        if capture := edit.get("capture"):
            module, symbol = capture.split(":")
            assert module == "retobs_adapter"
            assert f"\n{symbol} = " in (root / "retobs_adapter.py").read_text(encoding="utf-8")
    for scenario in overrides.get("scenarios", []):
        assert set(scenario) == SCENARIO_KEYS, scenario
        assert scenario["command"].startswith("python ")
    if "entrypoint" in overrides:
        assert set(overrides["entrypoint"]) == {"file", "symbol", "kind"}
        assert (root / overrides["entrypoint"]["file"]).is_file()
