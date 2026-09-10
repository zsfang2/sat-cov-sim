from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
import pytest

from satellite_coverage.domain.validation import (
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


def _passed_report() -> ReferenceValidationReport:
    return ReferenceValidationReport(
        checks=(
            ValidationCheck("terrain", ValidationOutcome.PASSED),
            ValidationCheck("geometry", ValidationOutcome.PASSED),
            ValidationCheck("tle", ValidationOutcome.PASSED),
        )
    )


def _complete_candidate() -> ReferenceFrameCandidate:
    return ReferenceFrameCandidate(
        map_path="frames/region-a/000012/received_power_dbm.npy",
        map_checksum="sha256:map-digest",
        component_paths=(),
        region_id="region-a",
        frame_index=12,
        timestamp_utc=datetime(2025, 1, 1, 0, 2, tzinfo=timezone.utc),
        config_checksum="sha256:config-digest",
        source_checksums=(
            ("dem", "sha256:dem-digest"),
            ("tle", "sha256:tle-digest"),
        ),
        code_version="git:0123456789abcdef",
        generation_status=GenerationStatus.COMPLETE,
        terrain_enabled=True,
    )


def test_complete_provenance_and_required_checks_allow_registration():
    report = _passed_report()
    candidate = _complete_candidate()

    assert (
        qualify_reference_candidate(candidate)
        is ArtifactValidationStatus.REFERENCE_CANDIDATE
    )
    assert (
        register_reference_frame(candidate, report)
        is ArtifactValidationStatus.VALIDATED_REFERENCE
    )


def test_passed_checks_do_not_implicitly_upgrade_legacy_output():
    report = _passed_report()

    assert (
        report.artifact_status(terrain_enabled=True)
        is ArtifactValidationStatus.LEGACY_UNVALIDATED
    )


def test_bare_npy_cannot_be_registered_even_when_checks_pass(tmp_path):
    map_path = tmp_path / "received_power_dbm.npy"
    np.save(map_path, np.zeros((2, 2), dtype=np.float32))
    candidate = ReferenceFrameCandidate(map_path=str(map_path))

    with pytest.raises(
        ArtifactRegistrationBlocked,
        match=r"map_checksum.*component_paths_declaration.*region_id.*config_checksum",
    ):
        register_reference_frame(candidate, _passed_report())


def test_missing_physical_check_blocks_complete_candidate_first():
    report = ReferenceValidationReport(
        checks=(
            ValidationCheck("terrain", ValidationOutcome.PASSED),
            ValidationCheck("geometry", ValidationOutcome.PASSED),
        )
    )

    with pytest.raises(ReferenceGenerationBlocked, match="tle"):
        register_reference_frame(_complete_candidate(), report)


def test_cf01_invalidated_artifact_cannot_transition_to_validated_reference():
    candidate = replace(
        _complete_candidate(),
        prior_status=ArtifactValidationStatus.INVALIDATED_BY_CF_01,
    )

    with pytest.raises(ArtifactRegistrationBlocked, match="prior_status"):
        register_reference_frame(candidate, _passed_report())


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


@pytest.mark.parametrize(
    ("overrides", "field_name"),
    [
        ({"component_paths": None}, "component_paths_declaration"),
        ({"timestamp_utc": datetime(2025, 1, 1)}, "timestamp_utc"),
        ({"source_checksums": ()}, "source_checksums"),
        ({"generation_status": GenerationStatus.INCOMPLETE}, "generation_status"),
    ],
)
def test_incomplete_or_malformed_provenance_is_rejected(overrides, field_name):
    with pytest.raises(ArtifactRegistrationBlocked, match=field_name):
        register_reference_frame(
            replace(_complete_candidate(), **overrides),
            _passed_report(),
        )
