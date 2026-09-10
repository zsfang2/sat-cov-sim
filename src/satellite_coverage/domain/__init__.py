"""Shared domain types with no data-source or output dependencies."""

from .release import (
    ImpactAnswer,
    NumericalChangeKind,
    NumericalChangeRecord,
    RegenerationApproval,
    RegenerationBlocked,
    RegenerationEvidence,
    RegenerationScope,
    require_regeneration_ready,
)
from .validation import (
    ArtifactRegistrationBlocked,
    ArtifactValidationStatus,
    GenerationStatus,
    ReferenceFrameCandidate,
    ReferenceGenerationBlocked,
    ReferenceValidationReport,
    ValidationCheck,
    ValidationOutcome,
    qualify_reference_candidate,
    register_reference_frame,
)

__all__ = [
    "ArtifactRegistrationBlocked",
    "ArtifactValidationStatus",
    "GenerationStatus",
    "ImpactAnswer",
    "NumericalChangeKind",
    "NumericalChangeRecord",
    "ReferenceFrameCandidate",
    "ReferenceGenerationBlocked",
    "ReferenceValidationReport",
    "RegenerationApproval",
    "RegenerationBlocked",
    "RegenerationEvidence",
    "RegenerationScope",
    "ValidationCheck",
    "ValidationOutcome",
    "qualify_reference_candidate",
    "register_reference_frame",
    "require_regeneration_ready",
]
