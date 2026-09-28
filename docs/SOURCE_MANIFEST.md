# Source Manifest and Path Resolution

External source bytes are identified separately from scenario parameters. A
`SourceManifest` is an immutable, canonical declaration of the exact files that a
run intends to use; it does not parse TLEs, open rasters, or authorize reference
generation.

## Schema version 1

Each source record requires all of these fields:

```yaml
source_id: dem-region-a
kind: dem
version: provider-release-or-acquisition-id
relative_path: dem/region-a.tif
checksum: sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
scope: regions
region_ids: [region-a]
horizontal_crs: EPSG:4326
vertical_crs: provider-declared-vertical-datum
```

Supported kinds are `tle_catalog`, `dem`, `building_vector`, `environment`,
`legacy_output`, and `source_metadata`. The last two identify old result arrays
and their accompanying evidence; they do not certify physical validity.
Scope is either `global` with an empty `region_ids` list or `regions` with one or
more stable region IDs. A TLE catalog is global. DEM records must declare both
horizontal and vertical CRS strings; the schema deliberately does not choose the
reference vertical datum.

The full document is:

```yaml
schema_version: 1
sources:
  - # one complete source record
```

The example values above describe the schema only. They are not a reference source
assignment. The actual four region footprints, provider artifacts, versions,
checksums, and vertical datum remain unfrozen, so no `configs/reference-sources.yaml`
is provided yet.

Each record identifies one regular file. Multi-file formats such as an unpacked
ESRI Shapefile, and tiled DEM collections consumed together, are represented by
multiple uniquely identified records with the same kind/region scope. Consumers
that support collections use `sources_for_region()`; `source_for_region()` fails
if more than one artifact matches, so a single-file loader cannot silently discard
tiles or sidecars. Recording only a `.shp` member while omitting its sidecars is not
complete provenance and must not be used for a reference run.

## Canonical identity

`SourceManifest.canonical_json_bytes()` sorts records by `source_id`, sorts mapping
keys, normalizes region ordering, and emits compact UTF-8 JSON. Its
`checksum_sha256()` method identifies the whole declaration. Each file checksum
must be lowercase `sha256:` followed by exactly 64 hexadecimal digits.

`manifest.provenance` converts each record to the path-free `SourceProvenance`
stored in physical domain state. `manifest.source_checksums` provides stable
`(source_id, checksum)` pairs for future dataset/release manifests.

## Portable local paths

Manifest paths use relative POSIX syntax. Absolute paths, Windows drive paths,
backslashes, empty segments, `.` segments, and `..` traversal are rejected. Runtime
location is injected separately with an explicit absolute source root:

```python
from pathlib import Path

from satellite_coverage.data_sources import SourceResolver, load_source_manifest

manifest_path = Path("/data/project/source-manifest.yaml")
manifest = load_source_manifest(manifest_path)
resolver = SourceResolver(manifest_path.parent.resolve())
resolved_dem = resolver.resolve(manifest.source_for("dem-region-a"))
```

`resolve()` always verifies that the resolved target remains inside the declared
root, is a regular file, and matches the recorded SHA-256. There is intentionally
no unverified resolution mode. Symlinks that leave the root, missing files, and
checksum mismatches fail closed with typed exceptions.

The resulting `ResolvedSource.path` is runtime-only and must not be serialized into
portable dataset metadata. Dataset writer/schema and environment provenance are
introduced later through their own public boundaries.
