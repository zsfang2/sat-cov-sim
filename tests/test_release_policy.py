from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from satellite_coverage.domain.release import (
    ImpactAnswer,
    NumericalChangeKind,
    NumericalChangeRecord,
    RegenerationApproval,
    RegenerationBlocked,
    RegenerationEvidence,
    RegenerationScope,
    require_regeneration_ready,
)
from satellite_coverage.domain.validation import (
    ReferenceValidationReport,
    ValidationCheck,
    ValidationOutcome,
)


def _passed_report() -> ReferenceValidationReport:
    return ReferenceValidationReport(
        checks=tuple(
            ValidationCheck(name, ValidationOutcome.PASSED)
            for name in ("terrain", "geometry", "tle")
        )
    )


def _cf01_change() -> NumericalChangeRecord:
    return NumericalChangeRecord(
        change_id="CF-01",
        kind=NumericalChangeKind.PHYSICS_MODEL_CORRECTION,
        components_affected=("terrain", "diffraction"),
        before_behavior="Receiver elevation is omitted from the terrain horizon.",
        after_behavior="Terrain visibility is evaluated receiver-relative.",
        validation_evidence=("flat-positive-elevation synthetic DEM",),
        current_generated_maps_change=ImpactAnswer.YES,
        published_benchmark_results_change=ImpactAnswer.POSSIBLY,
    )


def _complete_evidence() -> RegenerationEvidence:
    return RegenerationEvidence(
        validation_report=_passed_report(),
        all_acceptance_criteria_passed=True,
        pending_reference_decisions_resolved=True,
        p0_findings_closed=True,
        canonical_config_checksum="sha256:config",
        source_checksums=(
            ("dem", "sha256:dem"),
            ("tle", "sha256:tle"),
        ),
        random_stream_derivation="named-stream-v1",
        code_version="git:0123456789abcdef",
        environment_fingerprint="sha256:environment",
        writer_schema_version="satrm-v1",
        metadata_component_alignment_passed=True,
        small_sequence_dry_run_passed=True,
        legacy_disposition_policy="archive-and-mark-invalid",
        numerical_change_inventory_complete=True,
        numerical_change_records=(_cf01_change(),),
    )


def _approval(*, acknowledge_risk: bool = True) -> RegenerationApproval:
    return RegenerationApproval(
        approved_by="dataset-owner",
        approved_at_utc=datetime(2026, 9, 10, tzinfo=timezone.utc),
        scope=RegenerationScope.REFERENCE_DATASET,
        acknowledges_benchmark_recompute_risk=acknowledge_risk,
    )


def test_metadata_only_change_declares_no_numerical_impact():
    record = NumericalChangeRecord(
        change_id="GATE-01",
        kind=NumericalChangeKind.METADATA_OR_GATE_ONLY,
        components_affected=("validation",),
        before_behavior="Legacy output had no registration gate.",
        after_behavior="Reference registration requires provenance.",
        validation_evidence=("test_bare_npy_cannot_be_registered",),
        current_generated_maps_change=ImpactAnswer.NO,
        published_benchmark_results_change=ImpactAnswer.NO,
    )

    assert record.current_generated_maps_change is ImpactAnswer.NO


def test_cf01_fix_is_classified_as_map_affecting_with_benchmark_risk():
    record = _cf01_change()

    assert record.current_generated_maps_change is ImpactAnswer.YES
    assert record.published_benchmark_results_change is ImpactAnswer.POSSIBLY


def test_metadata_only_change_cannot_claim_map_changes():
    with pytest.raises(ValueError, match="map impact as no"):
        replace(
            NumericalChangeRecord(
                change_id="GATE-01",
                kind=NumericalChangeKind.METADATA_OR_GATE_ONLY,
                components_affected=("validation",),
                before_behavior="No gate.",
                after_behavior="Gate present.",
                validation_evidence=("unit test",),
                current_generated_maps_change=ImpactAnswer.NO,
                published_benchmark_results_change=ImpactAnswer.NO,
            ),
            current_generated_maps_change=ImpactAnswer.YES,
            published_benchmark_results_change=ImpactAnswer.POSSIBLY,
        )


def test_map_affecting_change_cannot_claim_no_benchmark_impact():
    with pytest.raises(ValueError, match="cannot claim no benchmark impact"):
        replace(
            _cf01_change(),
            published_benchmark_results_change=ImpactAnswer.NO,
        )


def test_complete_evidence_and_explicit_approval_allow_regeneration():
    require_regeneration_ready(_complete_evidence(), _approval())


def test_passed_checks_without_explicit_approval_still_block_regeneration():
    with pytest.raises(RegenerationBlocked, match="explicit_user_approval"):
        require_regeneration_ready(_complete_evidence(), None)


def test_approval_does_not_replace_missing_release_evidence():
    evidence = RegenerationEvidence(validation_report=_passed_report())

    with pytest.raises(
        RegenerationBlocked,
        match=r"all_acceptance_criteria_passed.*canonical_config_checksum",
    ):
        require_regeneration_ready(evidence, _approval())


def test_benchmark_risk_requires_separate_acknowledgement():
    with pytest.raises(
        RegenerationBlocked,
        match="benchmark_recompute_risk_acknowledgement",
    ):
        require_regeneration_ready(
            _complete_evidence(),
            _approval(acknowledge_risk=False),
        )
