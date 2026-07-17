"""Unit tests for Test Sets dataset export."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from retrieval_observatory.forge.datasets.exporter import export_dataset
from retrieval_observatory.forge.types import CorpusScenario, SyntheticDataset, SyntheticQuery


def _make_dataset() -> SyntheticDataset:
    corpus = {
        "d1": {"text": "Machine Learning is transforming technology.", "title": "ML Overview"},
        "d2": {"text": "Deep Learning builds on neural networks.", "title": "DL Guide"},
    }
    queries = [
        SyntheticQuery("q1", "What is machine learning?", "s1", "paraphrase", ["d1"], difficulty_label="easy"),
        SyntheticQuery("q2", "Explain deep learning.", "s1", "paraphrase", ["d2"], difficulty_label="medium"),
    ]
    qrels = {"q1": {"d1": 2}, "q2": {"d2": 2}}
    scenarios = [CorpusScenario("s1", "temporal", ["d1", "d2"], "Test scenario")]
    return SyntheticDataset(
        dataset_id="test_export",
        corpus=corpus,
        queries=queries,
        qrels=qrels,
        scenarios=scenarios,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


class TestBEIRExport:
    def setup_method(self):
        self.dataset = _make_dataset()
        self.tmpdir = tempfile.mkdtemp()

    def test_creates_output_dir(self):
        out = os.path.join(self.tmpdir, "test_beir")
        export_dataset(self.dataset, out, fmt="beir")
        assert Path(out).exists()

    def test_creates_corpus_jsonl(self):
        out = os.path.join(self.tmpdir, "beir_corpus")
        export_dataset(self.dataset, out, fmt="beir")
        corpus_path = Path(out) / "corpus.jsonl"
        assert corpus_path.exists()
        lines = corpus_path.read_text().strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert "_id" in first
        assert "text" in first

    def test_creates_queries_jsonl(self):
        out = os.path.join(self.tmpdir, "beir_queries")
        export_dataset(self.dataset, out, fmt="beir")
        q_path = Path(out) / "queries.jsonl"
        assert q_path.exists()
        lines = q_path.read_text().strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert "_id" in first
        assert "text" in first

    def test_creates_qrels_tsv(self):
        out = os.path.join(self.tmpdir, "beir_qrels")
        export_dataset(self.dataset, out, fmt="beir")
        qrels_path = Path(out) / "qrels" / "test.tsv"
        assert qrels_path.exists()
        lines = qrels_path.read_text().strip().splitlines()
        assert len(lines) == 2
        # Format: query_id \t 0 \t doc_id \t grade
        parts = lines[0].split("\t")
        assert len(parts) == 4
        assert parts[3] == "2"

    def test_creates_metadata_json(self):
        out = os.path.join(self.tmpdir, "beir_meta")
        export_dataset(self.dataset, out, fmt="beir")
        meta = json.loads((Path(out) / "forge_metadata.json").read_text())
        assert meta["dataset_id"] == "test_export"
        assert meta["schema_version"] == 1
        assert meta["total_queries"] == 2
        assert meta["corpus_size"] == 2


class TestCustomExport:
    def setup_method(self):
        self.dataset = _make_dataset()
        self.tmpdir = tempfile.mkdtemp()

    def test_custom_corpus_uses_id_field(self):
        out = os.path.join(self.tmpdir, "custom")
        export_dataset(self.dataset, out, fmt="custom")
        lines = (Path(out) / "corpus.jsonl").read_text().strip().splitlines()
        first = json.loads(lines[0])
        assert "id" in first

    def test_custom_queries_has_forge_metadata(self):
        out = os.path.join(self.tmpdir, "custom_q")
        export_dataset(self.dataset, out, fmt="custom")
        lines = (Path(out) / "queries.jsonl").read_text().strip().splitlines()
        first = json.loads(lines[0])
        assert "metadata" in first
        assert "difficulty_label" in first["metadata"]

    def test_custom_qrels_jsonl(self):
        out = os.path.join(self.tmpdir, "custom_qrels")
        export_dataset(self.dataset, out, fmt="custom")
        lines = (Path(out) / "qrels.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert "query_id" in first
        assert "doc_id" in first
        assert "grade" in first

    def test_returns_path_object(self):
        out = os.path.join(self.tmpdir, "ret_path")
        result = export_dataset(self.dataset, out, fmt="beir")
        assert isinstance(result, Path)
