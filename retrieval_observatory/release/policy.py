from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from retrieval_observatory.metrics.comparison import parse_metric_key


_POLICY_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_MANIFEST_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_SLICE_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


class _PolicyModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid", strict=True)


class PromotionEvidenceRequirements(_PolicyModel):
    required_manifest_fields: list[str] = Field(default_factory=list)
    min_label_coverage: float | None = Field(default=None, ge=0, le=1)
    max_sampled_out_rate: float | None = Field(default=None, ge=0, le=1)
    max_dropped_rate: float | None = Field(default=None, ge=0, le=1)

    @field_validator("required_manifest_fields")
    @classmethod
    def validate_manifest_fields(cls, fields: list[str]) -> list[str]:
        if len(fields) != len(set(fields)):
            raise ValueError("required manifest fields must be unique")
        if any(not _MANIFEST_FIELD.fullmatch(field) for field in fields):
            raise ValueError("required manifest fields must be exact dotted field paths")
        return fields


class LineageRequirements(_PolicyModel):
    require_stable_candidate_identity: bool = False
    min_input_output_coverage: float | None = Field(default=None, ge=0, le=1)
    require_recorded_exit_reasons: bool = False
    require_topology_alignment_for_diff: bool = True


class EvidenceRequirements(_PolicyModel):
    promotion: PromotionEvidenceRequirements = Field(default_factory=PromotionEvidenceRequirements)
    lineage_diagnosis: LineageRequirements = Field(default_factory=LineageRequirements)
    lineage_diff: LineageRequirements = Field(default_factory=LineageRequirements)


class StatisticsPolicy(_PolicyModel):
    confidence_level: float = Field(gt=0, lt=1)
    familywise_alpha: float = Field(gt=0, le=1)
    resamples: int = Field(ge=1)
    seed: int


class MetricGuard(_PolicyModel):
    metric: str
    direction: Literal["higher_is_better", "lower_is_better"]
    max_regression: float = Field(ge=0)
    min_paired_n: int = Field(ge=1)

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, metric: str) -> str:
        try:
            pipeline_id, stage_index, metric_name, k, branch_id = parse_metric_key(metric)
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError("metric selector must be an exact canonical metric key") from exc

        canonical = f"{pipeline_id}|stage{stage_index}|{metric_name}@{k}"
        if branch_id is not None:
            canonical += f"|branch={branch_id}"
        if not pipeline_id or not metric_name or branch_id == "" or canonical != metric:
            raise ValueError("metric selector must be an exact canonical metric key")
        return metric


class SliceGuard(_PolicyModel):
    id: str
    field: str
    value: str | int | float | bool | None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _POLICY_ID.fullmatch(value):
            raise ValueError("slice guard id must use lowercase letters, digits, '.', '_', or '-'")
        return value

    @field_validator("field")
    @classmethod
    def validate_field(cls, value: str) -> str:
        if not _SLICE_FIELD.fullmatch(value):
            raise ValueError("slice selector field must name one top-level metadata field")
        return value


class ReleasePolicy(_PolicyModel):
    id: str
    schema_version: Literal[2]
    digest: str | None = None
    evidence: EvidenceRequirements = Field(default_factory=EvidenceRequirements)
    statistics: StatisticsPolicy
    metrics: list[MetricGuard] = Field(min_length=1)
    slices: list[SliceGuard] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _POLICY_ID.fullmatch(value):
            raise ValueError("policy id must use lowercase letters, digits, '.', '_', or '-'")
        return value

    @model_validator(mode="after")
    def validate_guard_identities(self) -> ReleasePolicy:
        metric_ids = [guard.metric for guard in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("metric guard identities must be unique")
        slice_ids = [guard.id for guard in self.slices]
        if len(slice_ids) != len(set(slice_ids)):
            raise ValueError("slice guard identities must be unique")
        expected_digest = self._calculated_digest()
        if self.digest is not None and self.digest != expected_digest:
            raise ValueError("policy digest does not match the canonical policy content")
        self.digest = expected_digest
        return self

    def _calculated_digest(self) -> str:
        payload = {
            "id": self.id,
            "schema_version": self.schema_version,
            "evidence": self.evidence.model_dump(mode="json"),
            "statistics": self.statistics.model_dump(mode="json"),
            "metrics": [guard.model_dump(mode="json") for guard in self.metrics],
            "slices": [guard.model_dump(mode="json") for guard in self.slices],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def load_release_policy(path: str | Path) -> ReleasePolicy:
    policy_path = Path(path)
    payload = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    return ReleasePolicy.model_validate(payload)
