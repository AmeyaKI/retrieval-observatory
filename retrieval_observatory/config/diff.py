from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from retrieval_observatory.config.schema import ExperimentConfig, StageConfig


@dataclass
class StageDiff:
    index: int
    change: str  # "added" | "removed" | "changed" | "unchanged"
    before: Optional[Dict[str, Any]]
    after: Optional[Dict[str, Any]]


@dataclass
class PipelineDiff:
    pipeline_id: str
    change: str  # "added" | "removed" | "changed" | "unchanged"
    stage_diffs: List[StageDiff] = field(default_factory=list)


@dataclass
class ConfigDiff:
    dataset_changed: bool
    metrics_changed: bool
    pipeline_diffs: List[PipelineDiff]

    @property
    def has_changes(self) -> bool:
        return (
            self.dataset_changed
            or self.metrics_changed
            or any(p.change != "unchanged" for p in self.pipeline_diffs)
        )


def diff_configs(before: ExperimentConfig, after: ExperimentConfig) -> ConfigDiff:
    """Structural diff between two experiment configs: which pipelines/stages were added,
    removed, or changed. Pairs with `retobs compare` (outcome diff) to answer both "what
    changed" and "did it help"."""
    before_pipelines = {p.id: p for p in before.pipelines}
    after_pipelines = {p.id: p for p in after.pipelines}
    all_ids = sorted(set(before_pipelines) | set(after_pipelines))

    pipeline_diffs: List[PipelineDiff] = []
    for pid in all_ids:
        b = before_pipelines.get(pid)
        a = after_pipelines.get(pid)
        if b is None:
            pipeline_diffs.append(PipelineDiff(pipeline_id=pid, change="added"))
            continue
        if a is None:
            pipeline_diffs.append(PipelineDiff(pipeline_id=pid, change="removed"))
            continue
        stage_diffs = _diff_stages(b.stages, a.stages)
        change = "changed" if any(s.change != "unchanged" for s in stage_diffs) else "unchanged"
        pipeline_diffs.append(PipelineDiff(pipeline_id=pid, change=change, stage_diffs=stage_diffs))

    return ConfigDiff(
        dataset_changed=before.dataset.model_dump() != after.dataset.model_dump(),
        metrics_changed=before.metrics.model_dump() != after.metrics.model_dump(),
        pipeline_diffs=pipeline_diffs,
    )


def _diff_stages(before: List[StageConfig], after: List[StageConfig]) -> List[StageDiff]:
    diffs: List[StageDiff] = []
    max_len = max(len(before), len(after))
    for idx in range(max_len):
        b = before[idx].model_dump() if idx < len(before) else None
        a = after[idx].model_dump() if idx < len(after) else None
        if b is None:
            diffs.append(StageDiff(index=idx, change="added", before=None, after=a))
        elif a is None:
            diffs.append(StageDiff(index=idx, change="removed", before=b, after=None))
        elif b != a:
            diffs.append(StageDiff(index=idx, change="changed", before=b, after=a))
        else:
            diffs.append(StageDiff(index=idx, change="unchanged", before=b, after=a))
    return diffs
