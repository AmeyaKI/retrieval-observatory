from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet


class OverflowPolicy(str, Enum):
    DROP_NEWEST = "drop_newest"
    DROP_OLDEST = "drop_oldest"


@dataclass(frozen=True)
class RedactionRule:
    keys: FrozenSet[str] = frozenset(
        {
            "api_key",
            "authorization",
            "cookie",
            "password",
            "secret",
            "token",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "keys", frozenset(key.lower() for key in self.keys))


@dataclass(frozen=True)
class PayloadLimits:
    max_payload_bytes: int = 1_000_000
    max_candidates_per_span: int = 200
    max_string_chars: int = 8_192
    max_collection_items: int = 500
    max_depth: int = 8

    def __post_init__(self) -> None:
        for name in (
            "max_payload_bytes",
            "max_candidates_per_span",
            "max_string_chars",
            "max_collection_items",
            "max_depth",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class TelemetryConfig:
    queue_capacity: int = 1_000
    batch_size: int = 50
    flush_interval_s: float = 1.0
    shutdown_timeout_s: float = 5.0
    export_timeout_s: float = 3.0
    max_retries: int = 2
    retry_base_s: float = 0.1
    overflow_policy: OverflowPolicy = OverflowPolicy.DROP_NEWEST
    sample_rate: float = 1.0
    limits: PayloadLimits = field(default_factory=PayloadLimits)
    redaction: RedactionRule = field(default_factory=RedactionRule)

    def __post_init__(self) -> None:
        if self.queue_capacity <= 0:
            raise ValueError("queue_capacity must be positive")
        if not 0 < self.batch_size <= self.queue_capacity:
            raise ValueError("batch_size must be within queue capacity")
        if self.shutdown_timeout_s < 0:
            raise ValueError("shutdown_timeout_s must be non-negative")
        if self.export_timeout_s <= 0:
            raise ValueError("export_timeout_s must be positive")
        if self.flush_interval_s <= 0:
            raise ValueError("flush_interval_s must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.retry_base_s < 0:
            raise ValueError("retry_base_s must be non-negative")
        if not 0 <= self.sample_rate <= 1:
            raise ValueError("sample_rate must be between 0 and 1")
