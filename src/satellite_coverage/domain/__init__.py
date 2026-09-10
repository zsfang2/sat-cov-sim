"""Shared domain types with no data-source or output dependencies."""

from .validation import (
    ArtifactValidationStatus,
    ReferenceGenerationBlocked,
    ReferenceValidationReport,
    ValidationCheck,
    ValidationOutcome,
)

__all__ = [
    "ArtifactValidationStatus",
    "ReferenceGenerationBlocked",
    "ReferenceValidationReport",
    "ValidationCheck",
    "ValidationOutcome",
]

