"""Shared domain types with no data-source or output dependencies."""

from .validation import (
    ArtifactRegistrationBlocked,
    ArtifactValidationStatus,
    GenerationStatus,
    ReferenceFrameCandidate,
    ReferenceGenerationBlocked,
    ReferenceValidationReport,
    ValidationCheck,
    ValidationOutcome,
    register_reference_frame,
)

__all__ = [
    "ArtifactRegistrationBlocked",
    "ArtifactValidationStatus",
    "GenerationStatus",
    "ReferenceFrameCandidate",
    "ReferenceGenerationBlocked",
    "ReferenceValidationReport",
    "ValidationCheck",
    "ValidationOutcome",
    "register_reference_frame",
]
