"""scripts/study_loss_attribution.py declares the pre-registered grid and is idempotent."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def _load():
    path = ROOT / "scripts" / "study_loss_attribution.py"
    spec = importlib.util.spec_from_file_location("study_loss_attribution", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


driver = _load()


def test_grid_matches_the_preregistration():
    cells = driver.grid()
    ids = [cell.id for cell in cells]
    assert len(cells) == 14 and len(set(ids)) == 14
    for dataset in ("nfcorpus", "scifact", "fiqa"):
        for pipeline in ("bm25_only", "dense_only", "rrf_hybrid", "hybrid_rerank"):
            assert f"{dataset}__{pipeline}" in ids
    assert ids[-2:] == ["fiqa__bm25_rerank", "hotpotqa__hotpot_routed"]
    assert [cell.id for cell in cells if cell.reconciliation_only] == ["fiqa__bm25_rerank"]


@pytest.mark.parametrize("pipeline", ["bm25_only", "dense_only", "rrf_hybrid", "hybrid_rerank", "bm25_rerank"])
def test_beir_graphs_validate_with_the_declared_widths(pipeline):
    graph = driver.beir_graph(pipeline)
    nodes = {node.id: node for node in graph.nodes}
    assert graph.output == list(nodes)[-1]
    for node in nodes.values():
        assert node.op_type in {"SOURCE", "FUSE", "RERANK"}
    if "bm25" in nodes:
        assert nodes["bm25"].config["k"] == 100
    if "dense" in nodes:
        assert nodes["dense"].config == {
            "model": driver.DENSE_MODEL, "k": 100, "batch_size": 64, "cache_dir": str(driver.CACHE_DIR),
        }
        assert Path(nodes["dense"].config["cache_dir"]).is_relative_to(ROOT / ".retobs" / "study" / "cache")
    if "fuse" in nodes:
        assert nodes["fuse"].inputs == ["bm25", "dense"] and nodes["fuse"].config == {"rrf_k": 60, "top_k": 100, "fetch_k": 100}
    if "rerank" in nodes:
        # Full re-order recorded: ranks past 10 are kept, so a displaced gold has a rank.
        assert nodes["rerank"].config["k"] == 100 and nodes["rerank"].config["model"] == driver.CROSS_ENCODER
        assert nodes["rerank"].inputs == ["bm25" if pipeline == "bm25_rerank" else "fuse"]


def test_beir_config_records_no_latency_and_fixes_execution():
    build = {"git_sha": "abc1234", "retobs_version": "x"}
    cfg = driver.beir_config("scifact", driver.beir_graph("hybrid_rerank"), Path("/tmp/x.db"), build)
    assert cfg.dataset.name == "beir/scifact" and cfg.dataset.split == "test"
    assert cfg.metrics.latency_percentiles == [] and cfg.metrics.ndcg_at_k == [10] and cfg.metrics.recall_at_k == [10]
    assert cfg.execution.concurrency == 1 and cfg.execution.seed == 17 and cfg.execution.cache_results is False
    assert cfg.release_identity.deployment_revision == "abc1234"
    assert cfg.release_identity.embedding_model_revision == driver.DENSE_MODEL
    assert cfg.release_identity.reranker_model_revision == driver.CROSS_ENCODER
    bm25_only = driver.beir_config("scifact", driver.beir_graph("bm25_only"), Path("/tmp/x.db"), build)
    assert bm25_only.release_identity.embedding_model_revision is None
    assert bm25_only.release_identity.reranker_model_revision is None


def test_completed_cell_is_skipped_without_running(tmp_path: Path):
    cell = driver.Cell("nfcorpus", "bm25_only")
    payload = {"cell": cell.id, "run_id": "deadbeef"}
    driver.cell_path(cell, tmp_path).write_text(json.dumps(payload), encoding="utf-8")
    logged: list[str] = []
    result = asyncio.run(
        driver.run_cell(
            cell, db_path=tmp_path / "none.db", out_dir=tmp_path, max_queries=None, estimate_only=False,
            log=lambda *parts, **_: logged.append(" ".join(map(str, parts))),
        )
    )
    assert result == payload
    assert not (tmp_path / "none.db").exists()
    assert any("skipping" in line for line in logged)


def test_smoke_runs_may_not_write_under_results_study(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["study", "--max-queries", "3"])
    with pytest.raises(SystemExit, match="outside results/study"):
        driver.main()


def test_hotpot_manifest_refuses_a_different_subset(tmp_path: Path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(driver, "HOTPOT_MANIFEST", manifest)
    source = {"sampling": {"seed": 20260803}, "fingerprints": {"queries.jsonl": "sha256:a"}}
    driver._write_hotpot_manifest(["q1", "q2"], source, lambda *a, **k: None)
    written = json.loads(manifest.read_text(encoding="utf-8"))
    assert written["query_ids"] == ["q1", "q2"] and written["n_queries"] == 2 and written["seed"] == 20260803
    driver._write_hotpot_manifest(["q1", "q2"], source, lambda *a, **k: None)  # identical: fine
    with pytest.raises(SystemExit, match="does not match"):
        driver._write_hotpot_manifest(["q1", "q3"], source, lambda *a, **k: None)
