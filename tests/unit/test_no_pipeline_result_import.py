from __future__ import annotations

from pathlib import Path


def test_no_pipeline_result_import_in_dashboard_or_metrics() -> None:
    root = Path(__file__).resolve().parents[2]
    targets = [
        root / "retrieval_observatory" / "dashboard",
        root / "retrieval_observatory" / "metrics",
    ]
    offenders: list[str] = []
    for target in targets:
        for path in target.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "from retrieval_observatory.types import" in text and "PipelineResult" in text:
                offenders.append(str(path))
                continue
            if "import retrieval_observatory.types" in text and "PipelineResult" in text:
                offenders.append(str(path))
    assert not offenders, f"PipelineResult references remain in dashboard/metrics: {offenders}"
