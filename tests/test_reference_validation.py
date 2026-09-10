from __future__ import annotations

import pytest

from satellite_coverage.domain.validation import (
    ArtifactValidationStatus,
    ReferenceGenerationBlocked,
    ReferenceValidationReport,
    ValidationCheck,
    ValidationOutcome,
)


def test_all_required_checks_allow_reference_generation():
    report = ReferenceValidationReport(
        checks=(
            ValidationCheck("terrain", ValidationOutcome.PASSED),
            ValidationCheck("geometry", ValidationOutcome.PASSED),
            ValidationCheck("tle", ValidationOutcome.PASSED),
        )
    )

    report.require_reference_ready()

    assert report.is_reference_ready
    assert report.blocking_checks == ()
    assert report.artifact_status(terrain_enabled=True) is ArtifactValidationStatus.VALIDATED_REFERENCE


def test_missing_or_failed_checks_block_reference_generation():
    report = ReferenceValidationReport(
        checks=(
            ValidationCheck("terrain", ValidationOutcome.FAILED, ("CF-01",)),
            ValidationCheck("tle", ValidationOutcome.PASSED),
        )
    )

    with pytest.raises(ReferenceGenerationBlocked, match=r"geometry.*terrain"):
        report.require_reference_ready()

    assert report.blocking_checks == ("geometry", "terrain")
    assert report.artifact_status(terrain_enabled=True) is ArtifactValidationStatus.INVALIDATED_BY_CF_01
    assert report.artifact_status(terrain_enabled=False) is ArtifactValidationStatus.LEGACY_UNVALIDATED


def test_missing_terrain_evidence_does_not_claim_a_specific_invalidation():
    report = ReferenceValidationReport()

    assert report.artifact_status(terrain_enabled=True) is ArtifactValidationStatus.LEGACY_UNVALIDATED


def test_duplicate_check_names_are_rejected():
    with pytest.raises(ValueError, match="Duplicate validation check"):
        ReferenceValidationReport(
            checks=(
                ValidationCheck("terrain", ValidationOutcome.PASSED),
                ValidationCheck("terrain", ValidationOutcome.FAILED),
            )
        )
