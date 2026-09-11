"""Versioned, checksummed external-data identities and resolution."""

from .manifest import (
    SOURCE_MANIFEST_SCHEMA_VERSION,
    ResolvedSource,
    SourceIntegrityError,
    SourceKind,
    SourceManifest,
    SourceManifestError,
    SourcePathError,
    SourceRecord,
    SourceResolver,
    SourceScope,
    checksum_sha256,
    load_source_manifest,
)

__all__ = [
    "SOURCE_MANIFEST_SCHEMA_VERSION",
    "ResolvedSource",
    "SourceIntegrityError",
    "SourceKind",
    "SourceManifest",
    "SourceManifestError",
    "SourcePathError",
    "SourceRecord",
    "SourceResolver",
    "SourceScope",
    "checksum_sha256",
    "load_source_manifest",
]
