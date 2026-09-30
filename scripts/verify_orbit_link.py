"""Measure M1 coordinate/composition consistency from an archived run.

PROJ is an independent implementation of the receiver coordinate conversion.
Skyfield topocentric comparison shares orbit propagation and does not validate
physical orbit accuracy. The input TLE is loaded from the archive, not a live feed.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer

from satellite_coverage.geometry.geodetic import antenna_position, ecef_and_basis
from satellite_coverage.io.run_record import write_json
from satellite_coverage.orbit.visibility import altitude, parse_catalog, select_record, utc


def verify(run):
    result = json.loads((run / "links.json").read_text())
    data = result["request"]
    source = data.get("source", data)
    receiver = antenna_position(data["receiver"])
    xyz, _ = ecef_and_basis(receiver)
    reference = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True).transform(
        receiver["lon_deg"], receiver["lat_deg"], receiver["antenna_ellipsoid_height_m"])
    catalog = parse_catalog((run / "input.tle").read_bytes())
    sat = select_record(catalog.records[source["norad_id"]], utc(data["start"]), source["tle_policy"])
    records = result["records"]
    if sat is None or not result["complete"]:
        raise ValueError("verification requires a complete propagated run")
    times = [utc(r["timestamp_utc"]).timestamp() for r in records]
    elevation, azimuth, distance = altitude(sat, {"lon": receiver["lon_deg"], "lat": receiver["lat_deg"],
                                               "height_m": receiver["antenna_ellipsoid_height_m"]}, times)
    geometry = [r["geometry"] for r in records]
    known = [r["budget"] for r in records if r["budget"]["received_power"]["status"] == "known"]
    if not known:
        raise ValueError("verification requires some known powers")
    reassembly = [abs(b["received_power"]["value"] - (b["eirp_dbm"] + b["receiver_gain_dbi"] -
                   sum(c["quantity"]["value"] for c in b["components"]))) for b in known]
    metrics = {
        "receiver_ecef_proj_max_error_m": float(np.max(np.abs(np.asarray(xyz)-reference))),
        "topocentric_range_max_error_m": float(np.max(np.abs(np.array([g["slant_range_m"] for g in geometry])-distance*1000))),
        "topocentric_elevation_max_error_deg": float(np.max(np.abs(np.array([g["elevation_deg"] for g in geometry])-elevation))),
        "topocentric_azimuth_max_error_deg": max(abs((g["azimuth_deg"]-a+180)%360-180) for g, a in zip(geometry, azimuth) if g["azimuth_deg"] is not None),
        "power_reassembly_max_error_db": max(reassembly),
    }
    limits = dict(zip(metrics, (1e-8, 1e-5, 1e-8, 1e-8, 1e-6)))
    return {"run": str(run), "config_checksum": result["config_checksum"], "selection": result["selection"],
            "source_fingerprint": json.loads((run / "environment.json").read_text())["source_fingerprint"],
            "samples": len(records), "known_power_samples": len(known),
            "observed_errors": metrics, "tolerances": limits,
            "passed": all(metrics[k] <= limits[k] for k in metrics),
            "scope": "implementation consistency only; not orbit truth, terrain or service validation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, report)
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
