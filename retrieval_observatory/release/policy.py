from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from retrieval_observatory.metrics.comparison import parse_metric_key


_POLICY_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_MANIFEST_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_SLICE_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

# v3 selector vocabulary. Ranking metrics are computed on retrieved lists; query-level metrics
# describe the whole query (end-to-end latency, the failure indicator) and have no cutoff.
METRIC_NAMES = ("recall", "precision", "ndcg", "mrr", "map", "latency_ms", "failure_rate")
RANKING_METRICS = ("recall", "precision", "ndcg", "mrr", "map")
CUTOFF_METRICS = ("recall", "precision", "ndcg")
QUERY_LEVEL_METRICS = ("latency_ms", "failure_rate")
FINAL_RETRIEVAL = "final_retrieval"
OPERATOR_SELECTOR_PREFIX = "operator:"
_OPERATOR_SELECTOR = re.compile(r"^operator:\S+$")

# Intervention fields a policy may declare as expected between baseline and candidate.
INTERVENTION_FIELDS = (
    "reranker_model_revision",
    "embedding_model_revision",
    "index_build_id",
    "chunking_revision",
    "deployment_revision",
    "retriever_configuration",
)


class _PolicyModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid", strict=True)


class PromotionEvidenceRequirements(_PolicyModel):
    required_manifest_fields: list[str] = Field(default_factory=list)
    min_label_coverage: float | None = Field(default=None, ge=0, le=1)
    max_sampled_out_rate: float | None = Field(default=None, ge=0, le=1)
    max_dropped_rate: float | None = Field(default=None, ge=0, le=1)
    require_lineage_readiness: bool = False

    @field_validator("required_manifest_fields")
    @classmethod
    def validate_manifest_fields(cls, fields: list[str]) -> list[str]:
        if len(fields) != len(set(fields)):
            raise ValueError("required manifest fields must be unique")
        if any(not _MANIFEST_FIELD.fullmatch(field) for field in fields):
            raise ValueError("required manifest fields must be exact dotted field paths")
        return fields


class StageEquivalence(_PolicyModel):
    baseline_op_id: str = Field(min_length=1, pattern=r"^\S+$")
    candidate_op_id: str = Field(min_length=1, pattern=r"^\S+$")


class LineageRequirements(_PolicyModel):
    require_stable_candidate_identity: bool = False
    min_input_output_coverage: float | None = Field(default=None, ge=0, le=1)
    require_recorded_exit_reasons: bool = False
    require_topology_alignment_for_diff: bool = True
    equivalent_stages: list[StageEquivalence] = Field(default_factory=list)

    @field_validator("equivalent_stages")
    @classmethod
    def validate_equivalent_stages(
        cls, mappings: list[StageEquivalence]
    ) -> list[StageEquivalence]:
        baseline_ids = [mapping.baseline_op_id for mapping in mappings]
        candidate_ids = [mapping.candidate_op_id for mapping in mappings]
        if len(baseline_ids) != len(set(baseline_ids)) or len(candidate_ids) != len(
            set(candidate_ids)
        ):
            raise ValueError("equivalent stage mappings must be one-to-one")
        return mappings


class InterventionDeclaration(_PolicyModel):
    expected_changes: list[str] = Field(default_factory=list)

    @field_validator("expected_changes")
    @classmethod
    def validate_expected_changes(cls, fields: list[str]) -> list[str]:
        if len(fields) != len(set(fields)):
            raise ValueError("expected changes must be unique")
        if any(field not in INTERVENTION_FIELDS for field in fields):
            raise ValueError(f"expected changes must name one of: {', '.join(INTERVENTION_FIELDS)}")
        return fields


class EvidenceRequirements(_PolicyModel):
    promotion: PromotionEvidenceRequirements = Field(default_factory=PromotionEvidenceRequirements)
    lineage_diagnosis: LineageRequirements = Field(default_factory=LineageRequirements)
    lineage_diff: LineageRequirements = Field(default_factory=LineageRequirements)
    # Turns an absent or unverified index/query encoder pair into a BLOCK instead of leaving
    # unknown provenance unknown.
    require_index_encoder_compatibility: bool = False


class StatisticsPolicy(_PolicyModel):
    confidence_level: float = Field(gt=0, lt=1)
    familywise_alpha: float = Field(gt=0, le=1)
    resamples: int = Field(ge=1)
    seed: int
    # Minimum share of attempted queries that must be paired before a guard can PASS. A
    # query that failed (TIMEOUT/ERROR) in one run has no quality rows there, so the paired
    # join drops it; below this coverage the guard is HOLD rather than a verdict on the
    # queries that happened to survive.
    min_pair_coverage: float = Field(default=0.95, ge=0, le=1)


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
    intervention: InterventionDeclaration = Field(default_factory=InterventionDeclaration)
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
            "intervention": self.intervention.model_dump(mode="json"),
            "statistics": self.statistics.model_dump(mode="json"),
            "metrics": [guard.model_dump(mode="json") for guard in self.metrics],
            "slices": [guard.model_dump(mode="json") for guard in self.slices],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _validate_operator_selector(value: str, allow_final: bool) -> str:
    if allow_final and value == FINAL_RETRIEVAL:
        return value
    if not _OPERATOR_SELECTOR.fullmatch(value):
        raise ValueError(f"must be {FINAL_RETRIEVAL} or operator:<operator_id>")
    return value


class EvaluationSpec(_PolicyModel):
    unit: Literal["document", "chunk"]
    # final_retrieval, or an operator selector applied to every final_retrieval check.
    boundary: str = FINAL_RETRIEVAL
    k: int = Field(ge=1)
    relevance_threshold: int = Field(default=1, ge=1)
    unjudged_metric_policy: Literal["zero_gain", "exclude"] = "zero_gain"
    comparison_scope: Literal["fixed_corpus"] = "fixed_corpus"

    @field_validator("boundary")
    @classmethod
    def validate_boundary(cls, value: str) -> str:
        return _validate_operator_selector(value, allow_final=True)


class EvidenceRequirementsV3(_PolicyModel):
    require_query_input_identity: bool = True
    require_judgment_identity: bool = True
    require_corpus_identity: bool = True
    require_index_encoder_compatibility: bool = False
    require_lineage_for_decision: bool = False

    @field_validator("require_query_input_identity", "require_judgment_identity", "require_corpus_identity")
    @classmethod
    def validate_identity_required(cls, value: bool, info: ValidationInfo) -> bool:
        # The fixed-corpus contract has no "ignore provenance" switch; a false here would be
        # declared and then silently ignored by the assessment.
        if not value:
            raise ValueError(f"{info.field_name} cannot be disabled under the fixed_corpus comparison scope")
        return value


class StatisticsPolicyV3(_PolicyModel):
    confidence_level: float = Field(gt=0, lt=1)
    familywise_alpha: float = Field(gt=0, le=1)
    resamples: int = Field(ge=1)
    seed: int
    # v3 defaults to full pairing; a lowered threshold is explicit in every report.
    min_pair_coverage: float = Field(default=1.0, ge=0, le=1)
    repeated_trials: str = "first_attempt"

    @field_validator("repeated_trials")
    @classmethod
    def validate_repeated_trials(cls, value: str) -> str:
        if value != "first_attempt":
            raise ValueError("repeated-trial aggregation is not supported; repeated_trials must be first_attempt")
        return value

    @model_validator(mode="after")
    def validate_thresholds(self) -> StatisticsPolicyV3:
        if self.confidence_level + self.familywise_alpha > 1:
            raise ValueError("confidence_level and familywise_alpha are contradictory: their sum exceeds 1")
        return self


class MetricCheck(_PolicyModel):
    id: str
    metric: str
    target: str
    direction: Literal["higher_is_better", "lower_is_better"]
    max_regression: float = Field(ge=0)
    min_paired_n: int = Field(ge=1)
    estimator: Literal["mean", "p50", "p95", "p99"] = "mean"
    k: int | None = Field(default=None, ge=1)
    pipeline: str | None = Field(default=None, min_length=1, pattern=r"^[^|\s]+$")

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _POLICY_ID.fullmatch(value):
            raise ValueError("metric check id must use lowercase letters, digits, '.', '_', or '-'")
        return value

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, value: str) -> str:
        if value not in METRIC_NAMES:
            raise ValueError(f"unknown metric name {value!r}; expected one of: {', '.join(METRIC_NAMES)}")
        return value

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        if value == "query":
            return value
        try:
            return _validate_operator_selector(value, allow_final=True)
        except ValueError as exc:
            raise ValueError(f"target must be {FINAL_RETRIEVAL}, query, or operator:<operator_id>") from exc

    @model_validator(mode="after")
    def validate_selector_consistency(self) -> MetricCheck:
        # `mean` is the only estimator of a non-latency metric, so only another one is an error.
        if self.estimator != "mean" and self.metric != "latency_ms":
            raise ValueError(f"estimator applies only to latency_ms, not to {self.metric}")
        if self.k is not None and self.metric not in CUTOFF_METRICS:
            raise ValueError(f"k applies only to {', '.join(CUTOFF_METRICS)}, not to {self.metric}")
        if self.target == "query" and self.metric in RANKING_METRICS:
            raise ValueError(f"target query cannot carry the ranking metric {self.metric}; use final_retrieval")
        if self.target == FINAL_RETRIEVAL and self.metric in QUERY_LEVEL_METRICS:
            raise ValueError(f"{self.metric} is a query-level metric; use target query, not final_retrieval")
        if self.target.startswith(OPERATOR_SELECTOR_PREFIX) and self.metric == "failure_rate":
            raise ValueError("failure_rate is recorded per query, not per operator; use target query")
        return self


class SliceCheck(SliceGuard):
    # Empty means every declared metric check.
    metric_ids: list[str] = Field(default_factory=list)

    @field_validator("metric_ids")
    @classmethod
    def validate_metric_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("slice metric_ids must be unique")
        return values


class ExecutionPolicy(_PolicyModel):
    max_failure_rate: float = Field(default=0.0, ge=0, le=1)


class ReleasePolicyV3(_PolicyModel):
    id: str
    schema_version: Literal[3]
    digest: str | None = None
    evaluation: EvaluationSpec
    intervention: InterventionDeclaration = Field(default_factory=InterventionDeclaration)
    evidence: EvidenceRequirementsV3 = Field(default_factory=EvidenceRequirementsV3)
    statistics: StatisticsPolicyV3
    metrics: list[MetricCheck] = Field(min_length=1)
    slices: list[SliceCheck] = Field(default_factory=list)
    execution: ExecutionPolicy = Field(default_factory=ExecutionPolicy)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _POLICY_ID.fullmatch(value):
            raise ValueError("policy id must use lowercase letters, digits, '.', '_', or '-'")
        return value

    @model_validator(mode="after")
    def validate_checks(self) -> ReleasePolicyV3:
        from retrieval_observatory.release.resolution import validate_bootstrap_resolution

        metric_ids = [check.id for check in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("metric check ids must be unique")
        slice_ids = [item.id for item in self.slices]
        if len(slice_ids) != len(set(slice_ids)):
            raise ValueError("slice ids must be unique")
        for item in self.slices:
            unknown = [metric_id for metric_id in item.metric_ids if metric_id not in metric_ids]
            if unknown:
                raise ValueError(f"slice {item.id} names unknown metric ids: {', '.join(unknown)}")
        validate_bootstrap_resolution(self)
        expected_digest = self._calculated_digest()
        if self.digest is not None and self.digest != expected_digest:
            raise ValueError("policy digest does not match the canonical policy content")
        self.digest = expected_digest
        return self

    def _calculated_digest(self) -> str:
        payload = {
            "id": self.id,
            "schema_version": self.schema_version,
            "evaluation": self.evaluation.model_dump(mode="json"),
            "intervention": self.intervention.model_dump(mode="json"),
            "evidence": self.evidence.model_dump(mode="json"),
            "statistics": self.statistics.model_dump(mode="json"),
            "metrics": [check.model_dump(mode="json") for check in self.metrics],
            "slices": [item.model_dump(mode="json") for item in self.slices],
            "execution": self.execution.model_dump(mode="json"),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def load_release_policy(path: str | Path) -> ReleasePolicy | ReleasePolicyV3:
    policy_path = Path(path)
    payload: Any = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    version = payload.get("schema_version") if isinstance(payload, Mapping) else None
    if version == 2:
        return ReleasePolicy.model_validate(payload)
    if version == 3:
        return ReleasePolicyV3.model_validate(payload)
    raise ValueError(f"unsupported policy schema_version: {version!r} (expected 2 or 3)")
