"""Fail-closed validation state for reference dataset generation."""

from __future__ import annotations

from dataclasses import dataclass
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


class ReferenceGenerationBlocked(RuntimeError):
    """Raised when required validation evidence is absent or failed."""


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
        """Classify an artifact without upgrading unvalidated legacy output."""

        if self.is_reference_ready:
            return ArtifactValidationStatus.VALIDATED_REFERENCE
        terrain_check = self.check_for("terrain")
        if (
            terrain_enabled
            and terrain_check is not None
            and terrain_check.outcome is ValidationOutcome.FAILED
            and "CF-01" in terrain_check.findings
        ):
            return ArtifactValidationStatus.INVALIDATED_BY_CF_01
        return ArtifactValidationStatus.LEGACY_UNVALIDATED
