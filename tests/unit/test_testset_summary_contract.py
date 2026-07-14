from __future__ import annotations

import json

import pytest

from retrieval_observatory.forge.stress.suite import StressTestSuite
from retrieval_observatory.forge.types import (
    CorpusScenario,
    SyntheticDataset,
    SyntheticQuery,
    TestSetSummary,
)
from retrieval_observatory.store.sqlite import SQLiteStore


def _dataset() -> SyntheticDataset:
    return SyntheticDataset(
        dataset_id="set",
        corpus={"doc": {"text": "text"}},
        scenarios=[CorpusScenario("scenario", "temporal", ["doc"], "evidence")],
        queries=[SyntheticQuery("query", "text", "scenario", "temporal", ["doc"], validated=True)],
        qrels={"query": {"doc": 2}},
    )


def test_dataset_and_suite_emit_identical_versioned_summary() -> None:
    dataset = _dataset()

    direct = dataset.summary()
    suite = StressTestSuite(dataset).summary()

    assert direct == suite
    assert direct["schema_version"] == 1
    assert direct["total_queries"] == 1
    assert direct["total_scenarios"] == 1
    assert direct["validation_coverage"] == 1.0


def test_legacy_summary_shapes_migrate_to_same_contract() -> None:
    synthetic_legacy = {
        "dataset_id": "set",
        "corpus_size": 1,
        "n_scenarios": 1,
        "n_queries": 1,
        "scenarios_by_type": {"temporal": 1},
        "queries_by_type": {"temporal": 1},
        "queries_by_difficulty": {"medium": 1},
        "validated": 1,
    }
    suite_legacy = {
        "total_scenarios": 1,
        "total_queries": 1,
        "corpus_size": 1,
        "by_scenario_type": {"temporal": 1},
        "by_query_type": {"temporal": 1},
        "by_difficulty": {"medium": 1},
        "validated": 1,
    }

    assert TestSetSummary.from_dict(synthetic_legacy).to_dict() == TestSetSummary.from_dict(
        suite_legacy,
        dataset_id="set",
    ).to_dict()


@pytest.mark.asyncio
async def test_legacy_stored_summary_is_adapted_on_read(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "summary.db"))
    await store.init_db()
    await store.save_forge_dataset("legacy", json.dumps({"n_queries": 3, "n_scenarios": 2}), "", "")

    summary = (await store.get_forge_datasets())[0]["summary"]

    assert summary["schema_version"] == 1
    assert summary["dataset_id"] == "legacy"
    assert summary["total_queries"] == 3
    assert summary["total_scenarios"] == 2
