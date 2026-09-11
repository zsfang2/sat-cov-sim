"""Shared domain types with no data-source or output dependencies."""

from .arrays import DomainArray
from .grid import RegionGrid
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
from .state import (
    EnvironmentalState,
    FrameState,
    OrbitState,
    PhysicalState,
    PixelGeometry,
    RegionStaticState,
    ServiceState,
    SourceProvenance,
)
from .units import (
    ArrayUnit,
    DomainStateError,
    WGS84_ECEF_CRS,
    WGS84_GEODETIC_CRS,
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
    "ArrayUnit",
    "ArtifactRegistrationBlocked",
    "ArtifactValidationStatus",
    "DomainArray",
    "DomainStateError",
    "EnvironmentalState",
    "FrameState",
    "GenerationStatus",
    "ImpactAnswer",
    "NumericalChangeKind",
    "NumericalChangeRecord",
    "OrbitState",
    "PhysicalState",
    "PixelGeometry",
    "ReferenceFrameCandidate",
    "ReferenceGenerationBlocked",
    "ReferenceValidationReport",
    "RegenerationApproval",
    "RegenerationBlocked",
    "RegenerationEvidence",
    "RegenerationScope",
    "RegionGrid",
    "RegionStaticState",
    "ServiceState",
    "SourceProvenance",
    "ValidationCheck",
    "ValidationOutcome",
    "WGS84_ECEF_CRS",
    "WGS84_GEODETIC_CRS",
    "qualify_reference_candidate",
    "register_reference_frame",
    "require_regeneration_ready",
]
