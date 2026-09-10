"""Fail-closed validation state for reference dataset generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


REQUIRED_REFERENCE_CHECKS = frozenset({"geometry", "terrain", "tle"})


class ValidationOutcome(str, Enum):
    """Result of one independently executable validation check."""

    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"


class ArtifactValidationStatus(str, Enum):
    """Provenance status assigned to a generated or legacy artifact."""

    LEGACY_UNVALIDATED = "legacy_unvalidated"
    INVALIDATED_BY_CF_01 = "invalidated_by_CF_01"
    VALIDATED_REFERENCE = "validated_reference"


class GenerationStatus(str, Enum):
    """Whether the producer completed the candidate frame successfully."""

    INCOMPLETE = "incomplete"
    COMPLETE = "complete"


class ReferenceGenerationBlocked(RuntimeError):
    """Raised when required validation evidence is absent or failed."""


class ArtifactRegistrationBlocked(RuntimeError):
    """Raised when a concrete frame lacks registration evidence."""


@dataclass(frozen=True)
class ValidationCheck:
    """Named validation result and optional stable finding identifiers."""

    name: str
    outcome: ValidationOutcome
    findings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise ValueError("Validation check name must be non-empty and trimmed")
        if self.outcome is ValidationOutcome.PASSED and self.findings:
            raise ValueError("A passed validation check cannot contain findings")


@dataclass(frozen=True)
class ReferenceFrameCandidate:
    """Storage-neutral evidence required to register one reference frame.

    ``component_paths=None`` means the producer made no declaration about
    component outputs. An empty tuple is an explicit declaration that no
    component outputs exist for this candidate.
    """

    map_path: str | None = None
    map_checksum: str | None = None
    component_paths: tuple[tuple[str, str], ...] | None = None
    region_id: str | None = None
    frame_index: int | None = None
    timestamp_utc: datetime | None = None
    config_checksum: str | None = None
    source_checksums: tuple[tuple[str, str], ...] = ()
    code_version: str | None = None
    generation_status: GenerationStatus = GenerationStatus.INCOMPLETE
    terrain_enabled: bool | None = None

    @property
    def registration_issues(self) -> tuple[str, ...]:
        """Return stable field names for absent or malformed evidence."""

        issues: list[str] = []
        if not _is_nonempty_text(self.map_path):
            issues.append("map_path")
        if not _is_nonempty_text(self.map_checksum):
            issues.append("map_checksum")
        if self.component_paths is None:
            issues.append("component_paths_declaration")
        elif not _named_values_are_valid(self.component_paths):
            issues.append("component_paths")
        if not _is_nonempty_text(self.region_id):
            issues.append("region_id")
        if (
            not isinstance(self.frame_index, int)
            or isinstance(self.frame_index, bool)
            or self.frame_index < 0
        ):
            issues.append("frame_index")
        if not _is_utc_datetime(self.timestamp_utc):
            issues.append("timestamp_utc")
        if not _is_nonempty_text(self.config_checksum):
            issues.append("config_checksum")
        if not self.source_checksums or not _named_values_are_valid(
            self.source_checksums
        ):
            issues.append("source_checksums")
        if not _is_nonempty_text(self.code_version):
            issues.append("code_version")
        if self.generation_status is not GenerationStatus.COMPLETE:
            issues.append("generation_status")
        if not isinstance(self.terrain_enabled, bool):
            issues.append("terrain_enabled")
        return tuple(issues)


@dataclass(frozen=True)
class ReferenceValidationReport:
    """Collection of validation evidence used as a reference-release gate."""

    checks: tuple[ValidationCheck, ...] = ()

    def __post_init__(self) -> None:
        names = [check.name for check in self.checks]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            joined = ", ".join(duplicates)
            raise ValueError(f"Duplicate validation check names: {joined}")

    def outcome_for(self, name: str) -> ValidationOutcome:
        check = self.check_for(name)
        if check is not None:
            return check.outcome
        return ValidationOutcome.NOT_RUN

    def check_for(self, name: str) -> ValidationCheck | None:
        for check in self.checks:
            if check.name == name:
                return check
        return None

    @property
    def blocking_checks(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in sorted(REQUIRED_REFERENCE_CHECKS)
            if self.outcome_for(name) is not ValidationOutcome.PASSED
        )

    @property
    def is_reference_ready(self) -> bool:
        return not self.blocking_checks

    def require_reference_ready(self) -> None:
        """Reject reference generation unless every required check passed."""

        if self.blocking_checks:
            joined = ", ".join(self.blocking_checks)
            raise ReferenceGenerationBlocked(
                f"Reference generation blocked by checks: {joined}"
            )

    def artifact_status(self, *, terrain_enabled: bool) -> ArtifactValidationStatus:
        """Classify legacy output without registering it as a reference."""

        terrain_check = self.check_for("terrain")
        if (
            terrain_enabled
            and terrain_check is not None
            and terrain_check.outcome is ValidationOutcome.FAILED
            and "CF-01" in terrain_check.findings
        ):
            return ArtifactValidationStatus.INVALIDATED_BY_CF_01
        return ArtifactValidationStatus.LEGACY_UNVALIDATED


def register_reference_frame(
    candidate: ReferenceFrameCandidate,
    report: ReferenceValidationReport,
) -> ArtifactValidationStatus:
    """Validate physical checks and frame provenance before registration."""

    report.require_reference_ready()
    issues = candidate.registration_issues
    if issues:
        joined = ", ".join(issues)
        raise ArtifactRegistrationBlocked(
            f"Reference frame registration blocked by evidence: {joined}"
        )
    return ArtifactValidationStatus.VALIDATED_REFERENCE


def _is_nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _is_utc_datetime(value: object) -> bool:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() == timedelta(0)
    except (OverflowError, TypeError, ValueError):
        return False


def _named_values_are_valid(values: object) -> bool:
    if not isinstance(values, tuple):
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
