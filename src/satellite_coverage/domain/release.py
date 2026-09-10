"""Fail-closed policy for numerical changes and dataset regeneration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .validation import ReferenceValidationReport


class ImpactAnswer(str, Enum):
    """Declared impact on an existing numerical result."""

    YES = "yes"
    NO = "no"
    POSSIBLY = "possibly"


class NumericalChangeKind(str, Enum):
    """Stable categories used by numerical migration records."""

    METADATA_OR_GATE_ONLY = "metadata_or_gate_only"
    PROVEN_NUMERICALLY_EQUIVALENT = "proven_numerically_equivalent"
    PHYSICS_MODEL_CORRECTION = "physics_model_correction"
    GEOMETRY_OR_ORBIT_CHANGE = "geometry_or_orbit_change"
    SCHEDULING_OR_FRAME_IDENTITY_CHANGE = "scheduling_or_frame_identity_change"
    RNG_OR_REALIZATION_CHANGE = "rng_or_realization_change"
    BENCHMARK_ONLY_CHANGE = "benchmark_only_change"
    UNKNOWN_NUMERICAL_RISK = "unknown_numerical_risk"


@dataclass(frozen=True)
class NumericalChangeRecord:
    """Auditable declaration of a change's numerical consequences."""

    change_id: str
    kind: NumericalChangeKind
    components_affected: tuple[str, ...]
    before_behavior: str
    after_behavior: str
    validation_evidence: tuple[str, ...]
    current_generated_maps_change: ImpactAnswer
    published_benchmark_results_change: ImpactAnswer

    def __post_init__(self) -> None:
        for field_name in ("change_id", "before_behavior", "after_behavior"):
            if not _is_nonempty_text(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be non-empty and trimmed")
        if not _unique_nonempty_text(self.components_affected):
            raise ValueError("components_affected must contain unique names")
        if not _unique_nonempty_text(self.validation_evidence):
            raise ValueError("validation_evidence must contain unique entries")
        if not isinstance(self.kind, NumericalChangeKind):
            raise TypeError("kind must be a NumericalChangeKind")
        if not isinstance(self.current_generated_maps_change, ImpactAnswer):
            raise TypeError("current_generated_maps_change must be an ImpactAnswer")
        if not isinstance(self.published_benchmark_results_change, ImpactAnswer):
            raise TypeError(
                "published_benchmark_results_change must be an ImpactAnswer"
            )

        no_map_kinds = {
            NumericalChangeKind.METADATA_OR_GATE_ONLY,
            NumericalChangeKind.PROVEN_NUMERICALLY_EQUIVALENT,
            NumericalChangeKind.BENCHMARK_ONLY_CHANGE,
        }
        if (
            self.kind in no_map_kinds
            and self.current_generated_maps_change is not ImpactAnswer.NO
        ):
            raise ValueError(f"{self.kind.value} must declare map impact as no")
        if self.kind in {
            NumericalChangeKind.METADATA_OR_GATE_ONLY,
            NumericalChangeKind.PROVEN_NUMERICALLY_EQUIVALENT,
        } and self.published_benchmark_results_change is not ImpactAnswer.NO:
            raise ValueError(
                f"{self.kind.value} must declare benchmark impact as no"
            )
        if (
            self.kind is NumericalChangeKind.UNKNOWN_NUMERICAL_RISK
            and self.current_generated_maps_change is not ImpactAnswer.POSSIBLY
        ):
            raise ValueError("unknown numerical risk must declare map impact as possibly")
        if (
            self.current_generated_maps_change is not ImpactAnswer.NO
            and self.published_benchmark_results_change is ImpactAnswer.NO
        ):
            raise ValueError(
                "a possible or actual map change cannot claim no benchmark impact"
            )


class RegenerationScope(str, Enum):
    """Operation authorized by a separate approval record."""

    REFERENCE_DATASET = "reference_dataset"


@dataclass(frozen=True)
class RegenerationApproval:
    """Explicit user authorization recorded separately from validation."""

    approved_by: str
    approved_at_utc: datetime
    scope: RegenerationScope
    acknowledges_benchmark_recompute_risk: bool

    def __post_init__(self) -> None:
        if not _is_nonempty_text(self.approved_by):
            raise ValueError("approved_by must be non-empty and trimmed")
        if not _is_utc_datetime(self.approved_at_utc):
            raise ValueError("approved_at_utc must be timezone-aware UTC")
        if not isinstance(self.scope, RegenerationScope):
            raise TypeError("scope must be a RegenerationScope")
        if not isinstance(self.acknowledges_benchmark_recompute_risk, bool):
            raise TypeError("benchmark risk acknowledgement must be boolean")


@dataclass(frozen=True)
class RegenerationEvidence:
    """Release evidence independent of any dataset storage backend."""

    validation_report: ReferenceValidationReport
    all_acceptance_criteria_passed: bool = False
    pending_reference_decisions_resolved: bool = False
    p0_findings_closed: bool = False
    canonical_config_checksum: str | None = None
    source_checksums: tuple[tuple[str, str], ...] = ()
    random_stream_derivation: str | None = None
    code_version: str | None = None
    environment_fingerprint: str | None = None
    writer_schema_version: str | None = None
    metadata_component_alignment_passed: bool = False
    small_sequence_dry_run_passed: bool = False
    legacy_disposition_policy: str | None = None
    numerical_change_inventory_complete: bool = False
    numerical_change_records: tuple[NumericalChangeRecord, ...] = ()

    @property
    def readiness_issues(self) -> tuple[str, ...]:
        """Return stable identifiers for every missing release prerequisite."""

        issues = [
            f"physical_check:{name}" for name in self.validation_report.blocking_checks
        ]
        required_flags = (
            ("all_acceptance_criteria_passed", self.all_acceptance_criteria_passed),
            (
                "pending_reference_decisions_resolved",
                self.pending_reference_decisions_resolved,
            ),
            ("p0_findings_closed", self.p0_findings_closed),
            (
                "metadata_component_alignment_passed",
                self.metadata_component_alignment_passed,
            ),
            ("small_sequence_dry_run_passed", self.small_sequence_dry_run_passed),
            (
                "numerical_change_inventory_complete",
                self.numerical_change_inventory_complete,
            ),
        )
        issues.extend(name for name, value in required_flags if value is not True)

        required_text = (
            ("canonical_config_checksum", self.canonical_config_checksum),
            ("random_stream_derivation", self.random_stream_derivation),
            ("code_version", self.code_version),
            ("environment_fingerprint", self.environment_fingerprint),
            ("writer_schema_version", self.writer_schema_version),
            ("legacy_disposition_policy", self.legacy_disposition_policy),
        )
        issues.extend(name for name, value in required_text if not _is_nonempty_text(value))
        if not _named_values_are_valid(self.source_checksums):
            issues.append("source_checksums")
        if not isinstance(self.numerical_change_records, tuple) or any(
            not isinstance(record, NumericalChangeRecord)
            for record in self.numerical_change_records
        ):
            issues.append("numerical_change_records")
        return tuple(issues)


class RegenerationBlocked(RuntimeError):
    """Raised when release evidence or explicit approval is incomplete."""


def require_regeneration_ready(
    evidence: RegenerationEvidence,
    approval: RegenerationApproval | None,
) -> None:
    """Reject reference regeneration unless evidence and approval are complete."""

    issues = list(evidence.readiness_issues)
    if approval is None:
        issues.append("explicit_user_approval")
    elif approval.scope is not RegenerationScope.REFERENCE_DATASET:
        issues.append("approval_scope")
    elif _benchmark_recompute_risk(evidence) and not (
        approval.acknowledges_benchmark_recompute_risk
    ):
        issues.append("benchmark_recompute_risk_acknowledgement")

    if issues:
        joined = ", ".join(issues)
        raise RegenerationBlocked(f"Reference regeneration blocked by: {joined}")


def _benchmark_recompute_risk(evidence: RegenerationEvidence) -> bool:
    return any(
        record.published_benchmark_results_change is not ImpactAnswer.NO
        for record in evidence.numerical_change_records
    )


def _is_nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _is_utc_datetime(value: object) -> bool:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() == timedelta(0)
    except (OverflowError, TypeError, ValueError):
        return False


def _unique_nonempty_text(values: object) -> bool:
    return (
        isinstance(values, tuple)
        and bool(values)
        and all(_is_nonempty_text(value) for value in values)
        and len(values) == len(set(values))
    )


def _named_values_are_valid(values: object) -> bool:
    if not isinstance(values, tuple) or not values:
        return False
    names: set[str] = set()
    for entry in values:
        if not isinstance(entry, tuple) or len(entry) != 2:
            return False
        name, value = entry
        if (
            not _is_nonempty_text(name)
            or not _is_nonempty_text(value)
            or name in names
        ):
            return False
        names.add(name)
    return True
