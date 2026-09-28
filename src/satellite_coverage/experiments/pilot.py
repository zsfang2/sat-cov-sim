"""CLI for analytic links and separately identified external-data audits."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time

import numpy as np
import yaml

from ..adapters.legacy_output import LabelSpec, audit_legacy_array, physical_values, verify_file
from ..config.pilot import exact_keys, identity, load_pilot_config
from ..data_sources.dem_audit import audit_dem_window
from ..data_sources.manifest import SourceResolver, checksum_sha256, load_source_manifest
from ..engine.analytic_link import calculate_link, free_space_loss_db
from ..geometry.local import relative_enu_geometry
from ..io.run_record import RunRecord, archive_sources, environment_record


def _inside(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("source path must be a relative path without parent traversal")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("source path escapes source root or is not a file")
    return path


def audit_data(spec_path, run, source_root=None):
    spec_path = Path(spec_path).resolve()
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    exact_keys(spec, {"schema_version", "source_root", "source_manifest", "legacy_samples", "dem",
                      "legacy_evidence_source_id", "legacy_config_source_id", "composition"}, "audit_spec")
    if type(spec["schema_version"]) is not int or spec["schema_version"] != 1:
        raise ValueError("audit schema_version must be 1")
    root = Path(source_root).resolve(strict=True) if source_root else (spec_path.parent / spec["source_root"]).resolve(strict=True)
    manifest_path = (spec_path.parent / spec["source_manifest"]).resolve(strict=True)
    manifest = load_source_manifest(manifest_path)
    run.write("source_manifest.json", manifest.to_mapping())
    run.write("audit_spec.json", spec)
    resolver = SourceResolver(root)
    files, hash_times = {}, {}
    for record in manifest.sources:
        start = time.perf_counter()
        files[record.source_id] = resolver.resolve(record).path
        hash_times[record.source_id] = time.perf_counter() - start
    evidence = json.loads(files[spec["legacy_evidence_source_id"]].read_text())
    snapshot_path = files[spec["legacy_config_source_id"]]
    snapshot = yaml.safe_load(snapshot_path.read_text())
    # Preserve upstream evidence, including fallbacks and missing satellite provenance.
    run.write("upstream_manifest.json", evidence)
    run.write("upstream_config_snapshot.json", snapshot)
    reports, arrays = {}, {}
    for item in spec["legacy_samples"]:
        exact_keys(item, {"source_id", "label_type", "unit", "included_effects", "evidence", "normalization", "affected_by_cf01"}, "legacy_sample")
        source_id = item["source_id"]
        if source_id in reports:
            raise ValueError("duplicate legacy sample source_id")
        path = files[source_id]
        record = manifest.source_for(source_id)
        prior_hash = "sha256:" + evidence["output_files"][path.name]["sha256"]
        if prior_hash != record.checksum:
            raise ValueError("upstream output checksum disagrees with source manifest")
        label = LabelSpec(item["label_type"], item["unit"], tuple(item["included_effects"]), item["evidence"],
                          item["normalization"], item["affected_by_cf01"])
        reports[source_id] = audit_legacy_array(path, label, record.checksum)
        if reports[source_id]["conversion_issue"]:
            raise ValueError(f"{source_id}: {reports[source_id]['conversion_issue']}")
        values, unit, kind = physical_values(np.load(path, allow_pickle=False), label)
        if unit != "dB" or kind not in {"net_loss", "path_loss"}:
            raise ValueError("stored loss composition requires dB loss labels")
        arrays[source_id] = values
    composition = spec["composition"]
    exact_keys(composition, {"total", "components", "tolerance_db"}, "composition")
    if not isinstance(composition["components"], list) or not composition["components"] or len(set(composition["components"])) != len(composition["components"]):
        raise ValueError("composition components must be nonempty and unique")
    tolerance = composition["tolerance_db"]
    if isinstance(tolerance, bool) or not isinstance(tolerance, (float, int)) or not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("composition tolerance must be finite and nonnegative")
    total = arrays[composition["total"]].astype(np.float64)
    pieces = [arrays[k].astype(np.float64) for k in composition["components"]]
    effects = set()
    for key in composition["components"]:
        current = set(reports[key]["included_effects"])
        if "unknown" in current or effects.intersection(current):
            raise ValueError("composition has unknown or duplicate effects")
        effects.update(current)
    if effects != set(reports[composition["total"]]["included_effects"]):
        raise ValueError("total and component effect declarations disagree")
    if any(a.shape != total.shape for a in pieces):
        raise ValueError("composition arrays must have identical shapes")
    difference = float(np.max(np.abs(total - sum(pieces))))
    if not np.isfinite(difference):
        raise ValueError("nonfinite composition difference")
    composition_result = {**composition, "max_absolute_error_db": difference, "passed": difference <= tolerance,
                          "meaning": "stored arithmetic consistency only; not independent physical validation"}
    # This DEM remains outside the strict SourceRecord DEM contract until its vertical datum is known.
    dem = spec["dem"]
    exact_keys(dem, {"relative_path", "checksum", "longitude_deg", "latitude_deg", "window_size_px", "vertical_crs", "vertical_unit", "origin_note"}, "dem")
    dem_path = _inside(root, dem["relative_path"])
    start = time.perf_counter()
    verify_file(dem_path, dem["checksum"])
    hash_times["dem_full_file"] = time.perf_counter() - start
    start = time.perf_counter()
    dem_report, heights, mask = audit_dem_window(dem_path, dem["longitude_deg"], dem["latitude_deg"],
                                               dem["window_size_px"], dem["vertical_crs"], dem["vertical_unit"])
    dem_read_s = time.perf_counter() - start
    np.save(run.path / "dem_window.npy", heights, allow_pickle=False)
    np.save(run.path / "dem_nodata_mask.npy", mask, allow_pickle=False)
    dem_report.update({"source_path": str(dem_path), "source_checksum": dem["checksum"],
                       "origin_note": dem["origin_note"], "window_checksum": checksum_sha256(run.path / "dem_window.npy"),
                       "mask_checksum": checksum_sha256(run.path / "dem_nodata_mask.npy"),
                       "derivation": "native window, no resampling; raw pixels and mask stored separately"})
    limitations = ["upstream generation commit and full satellite identity unavailable",
                  "upstream fallbacks retained; stored components do not prove physical correctness"]
    if not dem_report["elevation_metadata_and_window_complete"]:
        limitations.append("DEM vertical datum/unit or completeness unresolved; physical terrain use not qualified")
    limitations.append("terrain solver, vertical alignment and required horizon radius not validated by this audit")
    if any(r["conversion_issue"] for r in reports.values()):
        limitations.append("one or more labels cannot be converted to physical units")
    report = {"schema_version": 1, "legacy_samples": reports, "composition": composition_result,
              "upstream_fallbacks": evidence.get("fallbacks_used", []),
              "upstream_satellite_meta": evidence.get("satellite_meta"), "dem": dem_report,
              "limitations": limitations, "is_reference_validation": False}
    run.write("sample-audit.json", report)
    run.write("timings.json", {"hash_seconds": hash_times, "dem_window_read_s": dem_read_s,
                              "dem_window_shape": list(heights.shape)})
    inputs = {"usage": "audit_only_not_analytic_link_inputs", "source_root_runtime": str(root),
              "source_manifest_checksum": manifest.checksum_sha256(), "source_checksums": dict(manifest.source_checksums),
              "audit_spec_checksum": checksum_sha256(spec_path), "dem_checksum": dem["checksum"]}
    run.write("inputs.json", inputs)
    if not composition_result["passed"]:
        raise ValueError("stored component recomposition exceeds declared tolerance")
    return limitations


def benchmark_link(config, repetitions=5, batch_size=100):
    data = config.to_mapping()
    distance = relative_enu_geometry(data["satellite_relative_enu_m"])["slant_range_m"]
    jobs = {"geometry": lambda: relative_enu_geometry(data["satellite_relative_enu_m"]),
            "fspl": lambda: free_space_loss_db(distance, data["frequency_hz"]),
            "complete_record": lambda: calculate_link(config)}
    report = {}
    for name, job in jobs.items():
        job()
        times = []
        for _ in range(repetitions):
            start = time.perf_counter()
            for _ in range(batch_size):
                job()
            times.append((time.perf_counter() - start) / batch_size)
        report[name] = {"median_s_per_call": statistics.median(times), "min_s_per_call": min(times),
                        "max_s_per_call": max(times), "samples_s_per_call": times}
    return {"repetitions": repetitions, "batch_size": batch_size, "sample_count": 1,
            "execution_threads": 1, "timings": report,
            "scope": "in-process analytic calculation; not direction-table or orbit benchmark"}


def execute(command, config_path, output, source_root=None):
    run = RunRecord(output)
    try:
        root = Path(__file__).resolve().parents[3]
        env = environment_record(root)
        run.write("environment.json", env)
        archive_sources(root, run.path / "source_snapshot.zip")
        raw_path = Path(config_path).resolve(strict=True)
        run.write("config_source.json", {"path": str(raw_path), "checksum": checksum_sha256(raw_path),
                                         "text": raw_path.read_text(encoding="utf-8")})
        config = load_pilot_config(raw_path)
        data = config.to_mapping()
        run.write("config.json", data)
        run.write("link_records.json", [])
        run.write("inputs.json", {"config_checksum": config.checksum_sha256(), "seed": data["seed"]})
        if command == "validate-data":
            if data["audit_spec"] is None:
                raise ValueError("audit_spec is required for validate-data")
            limitations = audit_data(raw_path.parent / data["audit_spec"], run, source_root)
            run.finish("completed_with_limitations" if limitations else "completed", limitations=limitations)
        elif command == "run":
            record = calculate_link(config)
            record["code_identity"] = {"commit": env["code_commit"], "source_fingerprint": env["source_fingerprint"]}
            record["run_record"] = "environment.json"
            inputs = {"usage": "synthetic_link_only", "config_checksum": config.checksum_sha256(),
                      "physical_input_checksum": config.checksum_sha256(), "seed": data["seed"],
                      "external_files_consumed": [], "audit_spec_usage": "not_consumed_by_analytic_run"}
            record["inputs_checksum"] = identity(inputs)
            run.write("inputs.json", inputs)
            run.write("link_records.json", [record])
            run.write("timings.json", benchmark_link(config))
            run.finish("completed", result_status=record["received_power"]["status"],
                       applicability=record["applicability"], reference_validated=False)
        else:
            raise ValueError("unsupported pilot command")
        return run.path
    except Exception as exc:
        run.finish("failed", error_type=type(exc).__name__, reason=str(exc))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate-data", "run"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", help="New directory; existing directories are never overwritten")
    parser.add_argument("--source-root", help="Runtime override for audit data root")
    args = parser.parse_args(argv)
    output = args.output or "output/pilot/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    try:
        path = execute(args.command, args.config, output, args.source_root)
    except Exception as exc:
        print(f"pilot failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"{args.command}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
