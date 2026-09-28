from copy import deepcopy
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
import yaml

from satellite_coverage.adapters.legacy_output import (
    LabelSpec, audit_legacy_array, mean_absolute_error_db, physical_values,
)
from satellite_coverage.config.pilot import PilotConfig, load_pilot_config
from satellite_coverage.data_sources.dem_audit import audit_dem_window
from satellite_coverage.data_sources.manifest import checksum_sha256, SourceIntegrityError
from satellite_coverage.domain.link_record import (
    LossComponent, Quantity, QuantityStatus, compose_received_power,
)
from satellite_coverage.engine.analytic_link import calculate_link, free_space_loss_db
from satellite_coverage.experiments.pilot import execute
from satellite_coverage.geometry.local import relative_enu_geometry


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    return load_pilot_config(ROOT / "configs/pilot.yaml")


def test_analytic_geometry_and_power_against_independent_formulas(config):
    result = calculate_link(config)
    geometry = result["geometry"]
    assert geometry["slant_range_m"] == pytest.approx(550000, abs=0.001)
    assert geometry["elevation_deg"] == pytest.approx(45, abs=1e-6)
    assert geometry["azimuth_deg"] == pytest.approx(0, abs=1e-6)
    expected = 20 * math.log10(4 * math.pi * 550000 * 14.5e9 / 299792458)
    assert result["received_power"]["value"] == pytest.approx(55 - expected, abs=1e-6)
    assert result["margin"]["value"] is None
    assert result["service_eligibility"] == "unknown"
    assert relative_enu_geometry([0, 0, 1])["azimuth_deg"] is None
    assert relative_enu_geometry([1, 0, 1])["azimuth_deg"] == 90
    assert free_space_loss_db(0.5, 2e9) == pytest.approx(20 * math.log10(4 * math.pi * 0.5 * 2e9 / 299792458), abs=1e-6)


def test_frequency_distance_and_power_scaling(config):
    base = free_space_loss_db(550000, 14.5e9)
    delta = 20 * math.log10(2)
    assert free_space_loss_db(1100000, 14.5e9) - base == pytest.approx(delta, abs=1e-6)
    assert free_space_loss_db(550000, 29e9) - base == pytest.approx(delta, abs=1e-6)
    data = config.to_mapping()
    data["power"]["eirp_dbm"] += 3
    data["threshold"] = {"received_power_dbm": -120, "basis": "synthetic_test_only"}
    changed = calculate_link(PilotConfig.from_mapping(data))
    initial = calculate_link(config)
    assert changed["received_power"]["value"] - initial["received_power"]["value"] == pytest.approx(3, abs=1e-6)
    assert changed["margin"]["value"] == pytest.approx(changed["received_power"]["value"] + 120)
    data["power"] = {"mode": "transmit_power_gain", "transmit_power_dbm": 40, "transmit_gain_dbi": 15}
    assert calculate_link(PilotConfig.from_mapping(data))["received_power"] == initial["received_power"]


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf")])
def test_invalid_frequency_and_range_are_rejected(config, value):
    with pytest.raises(ValueError):
        free_space_loss_db(value, 1e9)
    data = config.to_mapping()
    data["frequency_hz"] = value
    with pytest.raises(ValueError):
        PilotConfig.from_mapping(data)


def test_config_is_strict_canonical_and_immutable(config):
    original = config.to_mapping()
    reversed_data = dict(reversed(list(original.items())))
    reversed_data["frequency_hz"] = int(reversed_data["frequency_hz"])
    assert PilotConfig.from_mapping(reversed_data).checksum_sha256() == config.checksum_sha256()
    changed = config.to_mapping()
    changed["receiver"]["height_agl_m"] = 3
    assert config.to_mapping()["receiver"]["height_agl_m"] == 2
    for key, value in (("frequency_hz", 1e9), ("environment_id", "another-version")):
        data = deepcopy(original)
        data[key] = value
        assert PilotConfig.from_mapping(data).checksum_sha256() != config.checksum_sha256()
    assert PilotConfig.from_mapping(changed).checksum_sha256() != config.checksum_sha256()
    for change in (lambda d: d.pop("losses"), lambda d: d.update(extra=1),
                   lambda d: d["power"].update(transmit_gain_dbi=15),
                   lambda d: d.update(satellite_relative_enu_m=[0, 0, 0]),
                   lambda d: d.update(solver_version="unimplemented-model")):
        data = deepcopy(original)
        change(data)
        with pytest.raises(ValueError):
            PilotConfig.from_mapping(data)


@pytest.mark.parametrize("state", ["unknown", "not_applicable", "not_computed", "failed"])
def test_unavailable_loss_does_not_become_zero(config, state):
    data = config.to_mapping()
    data["losses"]["local"] = {"value": None, "status": state, "reason": "test_missingness"}
    result = calculate_link(PilotConfig.from_mapping(data))
    assert result["received_power"]["value"] is None
    assert result["received_power"]["status"] in {"failed", "not_computed"}
    data["losses"]["local"]["value"] = 0
    with pytest.raises(ValueError):
        PilotConfig.from_mapping(data)


def test_negative_extra_loss_allowed_but_duplicate_effects_rejected():
    q = Quantity(-3, "dB", QuantityStatus.KNOWN, "declared_enhancement")
    c = LossComponent("local", q, ("local",), "test")
    assert compose_received_power(55, 0, (c,)).value == 58
    for duplicate in (c, LossComponent("other", q, ("local",), "test"),
                      LossComponent("antenna", q, ("transmit_gain",), "test")):
        with pytest.raises(ValueError):
            compose_received_power(55, 0, (c, duplicate))


def test_below_horizontal_is_not_service_or_valid_received_power(config):
    data = config.to_mapping()
    data["satellite_relative_enu_m"] = [0, 100, -1]
    record = calculate_link(PilotConfig.from_mapping(data))
    assert record["received_power"]["status"] == "not_applicable"
    assert record["service_eligibility"] == "unknown"


def test_adapter_unit_conversion_normalization_and_unknowns(tmp_path):
    dbw = LabelSpec("received_power", "dBW", ("free_space",), "explicit_fixture")
    dbm = LabelSpec("received_power", "dBm", ("free_space",), "explicit_fixture")
    assert mean_absolute_error_db(np.array([-150.]), dbw, np.array([-120.]), dbm) == 0
    normalized = LabelSpec("normalized", "dimensionless", ("free_space",), "explicit_fixture",
                           {"formula": "physical = stored * scale + offset", "scale": 20,
                            "offset": -140, "output_unit": "dBm", "output_label_type": "received_power"})
    assert mean_absolute_error_db(np.array([1.]), normalized, np.array([-120.]), dbm) == 0
    missing = LabelSpec("normalized", "dimensionless", ("free_space",), "missing_parameters")
    with pytest.raises(ValueError, match="normalization"):
        mean_absolute_error_db(np.array([1.]), missing, np.array([-120.]), dbm)
    with pytest.raises(ValueError, match="incompatible"):
        mean_absolute_error_db(np.array([1.]), dbm, np.array([1.]), LabelSpec("path_loss", "dB", ("free_space",), "test"))
    with pytest.raises(ValueError):
        physical_values(np.array([np.nan]), dbm)
    path = tmp_path / "opaque.npy"
    np.save(path, np.array([1.]))
    unknown = LabelSpec("unknown", "unknown", ("unknown",), "no reliable label")
    report = audit_legacy_array(path, unknown, checksum_sha256(path))
    assert report["physical_summary"] is None and report["conversion_issue"]
    affected = LabelSpec("path_loss", "dB", ("local",), "known legacy terrain", affected_by_cf01=True)
    assert audit_legacy_array(path, affected, checksum_sha256(path))["artifact_status"] == "invalidated_by_CF_01"
    with pytest.raises(SourceIntegrityError):
        audit_legacy_array(path, unknown, "sha256:" + "0" * 64)


def test_dem_window_preserves_nodata_and_pixel_centers(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    from pyproj import CRS
    path = tmp_path / "dem.tif"
    data = np.full((8, 8), 500, dtype="float32")
    data[4, 4] = 0
    # Embed the full CRS as real GeoTIFFs do; fixture creation does not need
    # Rasterio to resolve an authority code against a second PROJ database.
    wgs84_wkt = CRS.from_epsg(4326).to_wkt(version="WKT1_GDAL")
    with rasterio.open(path, "w", driver="GTiff", height=8, width=8, count=1,
                       dtype="float32", crs=wgs84_wkt, transform=from_origin(108, 35, .01, .01), nodata=0) as ds:
        ds.write(data, 1)
    report, values, mask = audit_dem_window(path, 108.045, 34.955, 4)
    assert values.shape == (4, 4) and mask.sum() == 1
    assert values[mask].item() == 0
    assert report["valid_fraction"] == 15 / 16
    assert report["first_pixel_center_in_source_crs"] == pytest.approx([108.025, 34.975])
    assert report["vertical_crs_status"] == "unknown"
    assert not report["physical_use_ready"]
    assert report["available_window_buffer_m"] > 0
    with pytest.raises(ValueError, match="cover"):
        audit_dem_window(path, 108.001, 34.999, 8)


def test_run_reproducibility_failure_record_and_overwrite_protection(tmp_path):
    import zipfile
    first, second = tmp_path / "a", tmp_path / "b"
    for output in (first, second):
        execute("run", ROOT / "configs/pilot.yaml", output)
    for name in ("config.json", "inputs.json", "link_records.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    artifacts = json.loads((first / "artifacts.json").read_text())
    env = json.loads((first / "environment.json").read_text())
    with zipfile.ZipFile(first / "source_snapshot.zip") as archive:
        import hashlib
        for name, checksum in env["source_files"].items():
            assert "sha256:" + hashlib.sha256(archive.read(name)).hexdigest() == checksum
    for name, digest in artifacts["files"].items():
        assert checksum_sha256(first / name) == digest
    with pytest.raises(FileExistsError):
        execute("run", ROOT / "configs/pilot.yaml", first)
    bad = tmp_path / "bad.yaml"
    bad.write_text("frequency_hz: 0\n")
    with pytest.raises(ValueError):
        execute("run", bad, tmp_path / "failed")
    failure = json.loads((tmp_path / "failed/validation.json").read_text())
    assert failure["status"] == "failed" and failure["reason"]
    assert (tmp_path / "failed/config_source.json").is_file()


def test_cli_from_fresh_interpreter(tmp_path):
    command = [sys.executable, "-c",
               "import sys; sys.path.insert(0, 'src'); from satellite_coverage.experiments.pilot import main; raise SystemExit(main(sys.argv[1:]))",
               "run", "--config", "configs/pilot.yaml", "--output", str(tmp_path / "cli")]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_fixture_expected_values_are_self_consistent():
    folder = ROOT / "tests/fixtures/analytic"
    ridge = json.loads((folder / "ridge.json").read_text())
    rise = ridge["ridge_elevation_m"] - ridge["receiver_ground_elevation_m"] - ridge["receiver_height_agl_m"]
    assert math.degrees(math.atan2(rise, ridge["ridge_north_distance_m"])) == ridge["expected_horizon_elevation_deg"]
    curve = json.loads((folder / "time_curve.json").read_text())
    assert sum(end - start for start, end in curve["expected_bad_intervals_s"]) == 3
    assert curve["margin_db"][4] is None


def test_data_audit_end_to_end_and_bad_hash_failure(tmp_path, config):
    import rasterio
    from rasterio.transform import from_origin
    from pyproj import CRS

    source = tmp_path / "sources"
    source.mkdir()
    np.save(source / "total.npy", np.full((4, 4), 100, dtype="float32"))
    np.save(source / "loss.npy", np.full((4, 4), 100, dtype="float32"))
    evidence = {"output_files": {name: {"sha256": checksum_sha256(source / name).split(":")[1]}
                                for name in ("total.npy", "loss.npy")},
                "fallbacks_used": ["synthetic_audit_fixture"], "satellite_meta": {}}
    (source / "manifest.json").write_text(json.dumps(evidence))
    (source / "config.yaml").write_text("synthetic: true\n")
    with rasterio.open(source / "dem.tif", "w", driver="GTiff", height=8, width=8, count=1,
                       dtype="float32", crs=CRS.from_epsg(4326).to_wkt(version="WKT1_GDAL"),
                       transform=from_origin(108, 35, .01, .01), nodata=0) as ds:
        ds.write(np.full((8, 8), 500, dtype="float32"), 1)
    records = []
    for name in ("total.npy", "loss.npy", "manifest.json", "config.yaml"):
        records.append({"source_id": name, "kind": "legacy_output" if name.endswith(".npy") else "source_metadata",
                        "relative_path": name, "checksum": checksum_sha256(source / name),
                        "version": "synthetic", "scope": "global", "region_ids": [],
                        "horizontal_crs": None, "vertical_crs": None})
    (tmp_path / "sources.yaml").write_text(yaml.safe_dump({"schema_version": 1, "sources": records}))
    spec = {"schema_version": 1, "source_root": "sources", "source_manifest": "sources.yaml",
            "legacy_evidence_source_id": "manifest.json", "legacy_config_source_id": "config.yaml",
            "legacy_samples": [{"source_id": name, "label_type": "path_loss", "unit": "dB",
                                "included_effects": ["free_space"], "evidence": "synthetic",
                                "normalization": None, "affected_by_cf01": False}
                               for name in ("total.npy", "loss.npy")],
            "composition": {"total": "total.npy", "components": ["loss.npy"], "tolerance_db": 1e-6},
            "dem": {"relative_path": "dem.tif", "checksum": checksum_sha256(source / "dem.tif"),
                    "longitude_deg": 108.045, "latitude_deg": 34.955, "window_size_px": 4,
                    "vertical_crs": None, "vertical_unit": None, "origin_note": "synthetic"}}
    (tmp_path / "audit.yaml").write_text(yaml.safe_dump(spec))
    data = config.to_mapping()
    data["audit_spec"] = "audit.yaml"
    config_path = tmp_path / "pilot.yaml"
    config_path.write_text(yaml.safe_dump(data))
    execute("validate-data", config_path, tmp_path / "valid")
    report = json.loads((tmp_path / "valid/sample-audit.json").read_text())
    assert report["composition"]["passed"]
    assert not report["dem"]["physical_use_ready"]
    assert (tmp_path / "valid/dem_nodata_mask.npy").is_file()
    np.save(source / "loss.npy", np.zeros((4, 4), dtype="float32"))
    with pytest.raises(SourceIntegrityError):
        execute("validate-data", config_path, tmp_path / "corrupt")
    failure = json.loads((tmp_path / "corrupt/validation.json").read_text())
    assert failure["status"] == "failed" and "checksum" in failure["reason"]
    assert (tmp_path / "corrupt/audit_spec.json").is_file()
