from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

import pytest
import yaml

from satellite_coverage.data_sources import (
    SourceIntegrityError,
    SourceKind,
    SourceManifest,
    SourceManifestError,
    SourcePathError,
    SourceRecord,
    ResolvedSource,
    SourceResolver,
    SourceScope,
    checksum_sha256,
    load_source_manifest,
)


def _checksum(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _record(
    *,
    source_id: str = "dem-region-a",
    kind: SourceKind = SourceKind.DEM,
    relative_path: str = "dem/region-a.tif",
    checksum: str | None = None,
    scope: SourceScope = SourceScope.REGIONS,
    region_ids: tuple[str, ...] = ("region-a",),
    horizontal_crs: str | None = "EPSG:4326",
    vertical_crs: str | None = "EPSG:3855",
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        kind=kind,
        version="2025-01-01",
        relative_path=relative_path,
        checksum=_checksum(b"dem-bytes") if checksum is None else checksum,
        scope=scope,
        region_ids=region_ids,
        horizontal_crs=horizontal_crs,
        vertical_crs=vertical_crs,
    )


def _tle_record() -> SourceRecord:
    return _record(
        source_id="tle-catalog",
        kind=SourceKind.TLE_CATALOG,
        relative_path="tle/catalog.tle",
        checksum=_checksum(b"tle-bytes"),
        scope=SourceScope.GLOBAL,
        region_ids=(),
        horizontal_crs=None,
        vertical_crs=None,
    )


def test_manifest_is_canonical_order_independent_and_exposes_provenance():
    dem = _record()
    tle = _tle_record()

    first = SourceManifest(schema_version=1, sources=(tle, dem))
    second = SourceManifest(schema_version=1, sources=(dem, tle))

    assert first.sources == (dem, tle)
    assert first.canonical_json_bytes() == second.canonical_json_bytes()
    assert first.checksum_sha256() == second.checksum_sha256()
    assert first.source_checksums == (
        (dem.source_id, dem.checksum),
        (tle.source_id, tle.checksum),
    )
    assert tuple(item.source_id for item in first.provenance) == (
        "dem-region-a",
        "tle-catalog",
    )
    assert first.provenance[0].checksum == dem.checksum


def test_manifest_mapping_and_yaml_loader_are_strict(tmp_path):
    mapping = {
        "schema_version": 1,
        "sources": [_tle_record().to_mapping(), _record().to_mapping()],
    }
    manifest_path = tmp_path / "sources.yaml"
    manifest_path.write_text(yaml.safe_dump(mapping), encoding="utf-8")

    loaded = load_source_manifest(manifest_path)

    assert loaded == SourceManifest.from_mapping(mapping)
    assert loaded.source_for("dem-region-a").kind is SourceKind.DEM
    assert loaded.source_for_region(SourceKind.DEM, "region-a").source_id == (
        "dem-region-a"
    )

    malformed = dict(mapping, unexpected=True)
    with pytest.raises(SourceManifestError, match="unknown keys"):
        SourceManifest.from_mapping(malformed)

    missing = dict(mapping)
    del missing["sources"]
    with pytest.raises(SourceManifestError, match="missing required keys"):
        SourceManifest.from_mapping(missing)


@pytest.mark.parametrize(
    "checksum",
    [
        "",
        "sha256:missing",
        "sha256:" + "A" * 64,
        "md5:" + "0" * 32,
        "0" * 64,
    ],
)
def test_source_record_rejects_missing_or_noncanonical_checksum(checksum):
    with pytest.raises(SourceManifestError, match="checksum"):
        _record(checksum=checksum)


@pytest.mark.parametrize(
    "relative_path",
    [
        "/absolute/source.tif",
        "../escape.tif",
        "dem/../escape.tif",
        "./dem.tif",
        "dem//source.tif",
        r"C:\data\source.tif",
        r"dem\source.tif",
    ],
)
def test_source_record_rejects_nonportable_paths(relative_path):
    with pytest.raises(SourceManifestError, match="relative_path"):
        _record(relative_path=relative_path)


def test_source_scope_and_dem_crs_are_explicit():
    with pytest.raises(SourceManifestError, match="region_ids"):
        _record(region_ids=())
    with pytest.raises(SourceManifestError, match="region_ids"):
        replace(_tle_record(), region_ids=("region-a",))
    with pytest.raises(SourceManifestError, match="scope"):
        replace(_tle_record(), scope=SourceScope.REGIONS, region_ids=("region-a",))
    with pytest.raises(SourceManifestError, match="horizontal_crs"):
        _record(horizontal_crs=None)
    with pytest.raises(SourceManifestError, match="vertical_crs"):
        _record(vertical_crs=None)


def test_manifest_rejects_duplicate_ids_and_ambiguous_region_coverage():
    dem = _record()
    with pytest.raises(SourceManifestError, match="duplicate source_id"):
        SourceManifest(schema_version=1, sources=(dem, dem))

    overlapping = _record(
        source_id="other-dem",
        relative_path="dem/other.tif",
        region_ids=("region-a", "region-b"),
    )
    manifest = SourceManifest(schema_version=1, sources=(dem, overlapping))
    assert manifest.sources_for_region(SourceKind.DEM, "region-a") == (
        dem,
        overlapping,
    )
    with pytest.raises(SourceManifestError, match="ambiguous.*region-a"):
        manifest.source_for_region(SourceKind.DEM, "region-a")

    with pytest.raises(SourceManifestError, match="schema_version"):
        SourceManifest(schema_version=True, sources=(dem,))


def test_resolver_returns_verified_file_under_explicit_root(tmp_path):
    content = b"dem-bytes"
    source_path = tmp_path / "dem" / "region-a.tif"
    source_path.parent.mkdir()
    source_path.write_bytes(content)
    record = _record(checksum=_checksum(content))

    resolved = SourceResolver(tmp_path).resolve(record)

    assert resolved.record is record
    assert resolved.path == source_path.resolve()
    assert checksum_sha256(source_path) == record.checksum


def test_resolver_fails_closed_on_checksum_mismatch(tmp_path):
    source_path = tmp_path / "dem" / "region-a.tif"
    source_path.parent.mkdir()
    source_path.write_bytes(b"changed")

    with pytest.raises(SourceIntegrityError, match="dem-region-a.*checksum"):
        SourceResolver(tmp_path).resolve(_record())


def test_resolved_source_cannot_be_constructed_without_verification(tmp_path):
    source_path = tmp_path / "source.tif"
    source_path.write_bytes(b"changed")
    with pytest.raises(SourceIntegrityError, match="checksum"):
        ResolvedSource(record=_record(), path=source_path)
    with pytest.raises(SourcePathError, match="absolute"):
        ResolvedSource(record=_record(), path=Path("relative.tif"))


def test_resolver_rejects_missing_directory_and_symlink_escape(tmp_path):
    with pytest.raises(SourcePathError, match="absolute"):
        SourceResolver("relative/root")
    with pytest.raises(SourcePathError, match="directory"):
        SourceResolver(tmp_path / "missing")

    outside = tmp_path / "outside.tif"
    outside.write_bytes(b"dem-bytes")
    root = tmp_path / "root"
    (root / "dem").mkdir(parents=True)
    (root / "dem" / "region-a.tif").symlink_to(outside)

    with pytest.raises(SourcePathError, match="escapes"):
        SourceResolver(root).resolve(_record())


def test_resolver_rejects_missing_source_and_directory_target(tmp_path):
    resolver = SourceResolver(tmp_path)
    with pytest.raises(SourcePathError, match="does not exist"):
        resolver.resolve(_record())

    target = tmp_path / "dem" / "region-a.tif"
    target.mkdir(parents=True)
    with pytest.raises(SourcePathError, match="regular file"):
        resolver.resolve(_record())
