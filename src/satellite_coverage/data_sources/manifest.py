"""Canonical identities and verified local resolution for external sources."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any, Mapping

from ..domain.state import SourceProvenance


SOURCE_MANIFEST_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_SOURCE_KEYS = frozenset(
    {
        "source_id",
        "kind",
        "version",
        "relative_path",
        "checksum",
        "scope",
        "region_ids",
        "horizontal_crs",
        "vertical_crs",
    }
)


class SourceManifestError(ValueError):
    """Raised when source identity or manifest data is incomplete or ambiguous."""


class SourcePathError(SourceManifestError):
    """Raised when a source cannot be resolved safely below its declared root."""


class SourceIntegrityError(SourceManifestError):
    """Raised when resolved source bytes do not match their declared checksum."""


class SourceKind(str, Enum):
    """Supported external input roles."""

    TLE_CATALOG = "tle_catalog"
    DEM = "dem"
    BUILDING_VECTOR = "building_vector"
    ENVIRONMENT = "environment"
    LEGACY_OUTPUT = "legacy_output"
    SOURCE_METADATA = "source_metadata"


class SourceScope(str, Enum):
    """Whether a source applies globally or only to named regions."""

    GLOBAL = "global"
    REGIONS = "regions"


@dataclass(frozen=True)
class SourceRecord:
    """Portable identity for one exact external source artifact."""

    source_id: str
    kind: SourceKind
    version: str
    relative_path: str
    checksum: str
    scope: SourceScope
    region_ids: tuple[str, ...]
    horizontal_crs: str | None
    vertical_crs: str | None

    def __post_init__(self) -> None:
        _require_text("source_id", self.source_id)
        _require_text("version", self.version)
        if not isinstance(self.kind, SourceKind):
            raise SourceManifestError("kind must be a supported SourceKind")
        if not isinstance(self.scope, SourceScope):
            raise SourceManifestError("scope must be a SourceScope")
        _validate_relative_path(self.relative_path)
        _validate_checksum(self.checksum)

        if not isinstance(self.region_ids, tuple):
            raise SourceManifestError("region_ids must be a tuple")
        for region_id in self.region_ids:
            _require_text("region_ids entry", region_id)
        if len(self.region_ids) != len(set(self.region_ids)):
            raise SourceManifestError("region_ids must be unique")
        object.__setattr__(self, "region_ids", tuple(sorted(self.region_ids)))

        if self.scope is SourceScope.GLOBAL and self.region_ids:
            raise SourceManifestError("global scope requires empty region_ids")
        if self.scope is SourceScope.REGIONS and not self.region_ids:
            raise SourceManifestError("regions scope requires non-empty region_ids")
        if self.kind is SourceKind.TLE_CATALOG and self.scope is not SourceScope.GLOBAL:
            raise SourceManifestError("tle_catalog scope must be global")

        _validate_optional_text("horizontal_crs", self.horizontal_crs)
        _validate_optional_text("vertical_crs", self.vertical_crs)
        if self.kind is SourceKind.DEM:
            if self.horizontal_crs is None:
                raise SourceManifestError("DEM horizontal_crs must be declared")
            if self.vertical_crs is None:
                raise SourceManifestError("DEM vertical_crs must be declared")

    @classmethod
    def from_mapping(cls, value: Any, *, path: str = "source") -> "SourceRecord":
        data = _require_mapping(path, value)
        _require_keys(path, data, _SOURCE_KEYS)
        try:
            kind = SourceKind(data["kind"])
        except (TypeError, ValueError) as exc:
            raise SourceManifestError(f"{path}.kind is unsupported") from exc
        try:
            scope = SourceScope(data["scope"])
        except (TypeError, ValueError) as exc:
            raise SourceManifestError(f"{path}.scope is unsupported") from exc
        region_ids = data["region_ids"]
        if not isinstance(region_ids, list):
            raise SourceManifestError(f"{path}.region_ids must be a list")
        try:
            return cls(
                source_id=data["source_id"],
                kind=kind,
                version=data["version"],
                relative_path=data["relative_path"],
                checksum=data["checksum"],
                scope=scope,
                region_ids=tuple(region_ids),
                horizontal_crs=data["horizontal_crs"],
                vertical_crs=data["vertical_crs"],
            )
        except SourceManifestError as exc:
            raise SourceManifestError(f"{path}: {exc}") from exc

    def to_mapping(self) -> dict[str, Any]:
        """Return a JSON/YAML-compatible canonical field mapping."""
        return {
            "source_id": self.source_id,
            "kind": self.kind.value,
            "version": self.version,
            "relative_path": self.relative_path,
            "checksum": self.checksum,
            "scope": self.scope.value,
            "region_ids": list(self.region_ids),
            "horizontal_crs": self.horizontal_crs,
            "vertical_crs": self.vertical_crs,
        }

    @property
    def provenance(self) -> SourceProvenance:
        """Return storage-neutral provenance for physical domain state."""
        return SourceProvenance(
            source_id=self.source_id,
            source_kind=self.kind.value,
            version=self.version,
            checksum=self.checksum,
        )

    def covers_region(self, region_id: str) -> bool:
        _require_text("region_id", region_id)
        return self.scope is SourceScope.GLOBAL or region_id in self.region_ids


@dataclass(frozen=True)
class SourceManifest:
    """Canonical collection of unambiguous source artifacts for one run."""

    schema_version: int
    sources: tuple[SourceRecord, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != SOURCE_MANIFEST_SCHEMA_VERSION
        ):
            raise SourceManifestError(
                f"schema_version must be {SOURCE_MANIFEST_SCHEMA_VERSION}"
            )
        if not isinstance(self.sources, tuple) or not self.sources:
            raise SourceManifestError("sources must be a non-empty tuple")
        if any(not isinstance(source, SourceRecord) for source in self.sources):
            raise SourceManifestError("sources must contain SourceRecord values")

        source_ids = tuple(source.source_id for source in self.sources)
        duplicates = sorted(
            source_id
            for source_id in set(source_ids)
            if source_ids.count(source_id) > 1
        )
        if duplicates:
            raise SourceManifestError(
                f"duplicate source_id values: {', '.join(duplicates)}"
            )
        object.__setattr__(
            self,
            "sources",
            tuple(sorted(self.sources, key=lambda source: source.source_id)),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "SourceManifest":
        data = _require_mapping("manifest", value)
        _require_keys("manifest", data, frozenset({"schema_version", "sources"}))
        source_values = data["sources"]
        if not isinstance(source_values, list):
            raise SourceManifestError("manifest.sources must be a list")
        return cls(
            schema_version=data["schema_version"],
            sources=tuple(
                SourceRecord.from_mapping(item, path=f"manifest.sources[{index}]")
                for index, item in enumerate(source_values)
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sources": [source.to_mapping() for source in self.sources],
        }

    def canonical_json_bytes(self) -> bytes:
        """Return deterministic bytes for embedding or content identity."""
        return json.dumps(
            self.to_mapping(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    def checksum_sha256(self) -> str:
        digest = hashlib.sha256(self.canonical_json_bytes()).hexdigest()
        return f"sha256:{digest}"

    @property
    def source_checksums(self) -> tuple[tuple[str, str], ...]:
        return tuple((source.source_id, source.checksum) for source in self.sources)

    @property
    def provenance(self) -> tuple[SourceProvenance, ...]:
        return tuple(source.provenance for source in self.sources)

    def source_for(self, source_id: str) -> SourceRecord:
        _require_text("source_id", source_id)
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise SourceManifestError(f"source_id is not declared: {source_id}")

    def source_for_region(
        self,
        kind: SourceKind,
        region_id: str,
    ) -> SourceRecord:
        if not isinstance(kind, SourceKind):
            raise SourceManifestError("kind must be a supported SourceKind")
        _require_text("region_id", region_id)
        matches = self.sources_for_region(kind, region_id)
        if not matches:
            raise SourceManifestError(
                f"no {kind.value} source is declared for region {region_id}"
            )
        if len(matches) > 1:
            source_ids = ", ".join(source.source_id for source in matches)
            raise SourceManifestError(
                f"ambiguous {kind.value} sources for region {region_id}: {source_ids}"
            )
        return matches[0]

    def sources_for_region(
        self,
        kind: SourceKind,
        region_id: str,
    ) -> tuple[SourceRecord, ...]:
        """Return all declared artifacts of a kind that cover one region."""
        if not isinstance(kind, SourceKind):
            raise SourceManifestError("kind must be a supported SourceKind")
        _require_text("region_id", region_id)
        return tuple(
            source
            for source in self.sources
            if source.kind is kind and source.covers_region(region_id)
        )


@dataclass(frozen=True)
class ResolvedSource:
    """Runtime-only verified path paired with its portable manifest record."""

    record: SourceRecord
    path: Path

    def __post_init__(self) -> None:
        if not isinstance(self.record, SourceRecord):
            raise SourcePathError("record must be a SourceRecord")
        try:
            path = Path(self.path)
        except TypeError as exc:
            raise SourcePathError("resolved source must be a filesystem path") from exc
        if not path.is_absolute():
            raise SourcePathError("resolved source path must be absolute")
        try:
            path = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SourcePathError(
                f"resolved source does not exist for {self.record.source_id}"
            ) from exc
        if not path.is_file():
            raise SourcePathError(
                f"resolved source must be a regular file for {self.record.source_id}"
            )
        actual_checksum = checksum_sha256(path)
        if not hmac.compare_digest(actual_checksum, self.record.checksum):
            raise SourceIntegrityError(
                f"source {self.record.source_id} checksum mismatch: expected "
                f"{self.record.checksum}, got {actual_checksum}"
            )
        object.__setattr__(self, "path", path)


@dataclass(frozen=True)
class SourceResolver:
    """Resolve and verify manifest paths under one explicit absolute root."""

    root: Path

    def __post_init__(self) -> None:
        try:
            root = Path(self.root)
        except TypeError as exc:
            raise SourcePathError("source root must be a filesystem path") from exc
        if not root.is_absolute():
            raise SourcePathError("source root must be absolute")
        try:
            root = root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SourcePathError(
                f"source root directory does not exist: {root}"
            ) from exc
        if not root.is_dir():
            raise SourcePathError(f"source root must be a directory: {root}")
        object.__setattr__(self, "root", root)

    def resolve(self, record: SourceRecord) -> ResolvedSource:
        if not isinstance(record, SourceRecord):
            raise SourcePathError("record must be a SourceRecord")
        relative = PurePosixPath(record.relative_path)
        candidate = self.root.joinpath(*relative.parts)
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SourcePathError(
                f"source does not exist for {record.source_id}: {record.relative_path}"
            ) from exc
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise SourcePathError(
                f"source path escapes root for {record.source_id}: "
                f"{record.relative_path}"
            ) from exc
        if not resolved.is_file():
            raise SourcePathError(
                f"source must be a regular file for {record.source_id}: "
                f"{record.relative_path}"
            )
        return ResolvedSource(record=record, path=resolved)


def checksum_sha256(path: str | Path) -> str:
    """Stream one regular file and return its canonical SHA-256 identity."""
    try:
        source_path = Path(path)
    except TypeError as exc:
        raise SourcePathError("checksum target must be a filesystem path") from exc
    if not source_path.is_file():
        raise SourcePathError(f"checksum target must be a regular file: {source_path}")
    digest = hashlib.sha256()
    try:
        with source_path.open("rb") as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SourcePathError(f"cannot read checksum target: {source_path}") from exc
    return f"sha256:{digest.hexdigest()}"


def load_source_manifest(path: str | Path) -> SourceManifest:
    """Load strict YAML manifest metadata without resolving source content."""
    import yaml

    manifest_path = Path(path)
    try:
        value = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SourceManifestError(f"cannot load source manifest: {manifest_path}") from exc
    return SourceManifest.from_mapping(value)


def _validate_relative_path(value: object) -> None:
    _require_text("relative_path", value)
    assert isinstance(value, str)
    if "\\" in value or "\x00" in value:
        raise SourceManifestError("relative_path must use portable POSIX separators")
    if PureWindowsPath(value).drive or PurePosixPath(value).is_absolute():
        raise SourceManifestError("relative_path must not be absolute or drive-qualified")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SourceManifestError(
            "relative_path must not contain empty, dot, or parent segments"
        )


def _validate_checksum(value: object) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise SourceManifestError(
            "checksum must use lowercase sha256:<64 hexadecimal digits>"
        )


def _validate_optional_text(name: str, value: object) -> None:
    if value is not None:
        _require_text(name, value)


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise SourceManifestError(f"{name} must be non-empty and trimmed")


def _require_mapping(path: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SourceManifestError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise SourceManifestError(f"{path} keys must be strings")
    return value


def _require_keys(
    path: str,
    value: Mapping[str, Any],
    required: frozenset[str],
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing:
        raise SourceManifestError(
            f"{path} missing required keys: {', '.join(missing)}"
        )
    if unknown:
        raise SourceManifestError(f"{path} has unknown keys: {', '.join(unknown)}")
