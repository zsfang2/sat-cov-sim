"""Conditional Copernicus DSM -> ellipsoid -> M1 integration experiment.

Requires an explicitly supplied, completely downloaded EGM2008 grid. Receiver
height is assumed to be two metres above the DSM, not a surveyed antenna AGL.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import yaml

from satellite_coverage.data_sources.manifest import checksum_sha256
from satellite_coverage.data_sources.terrain_dem import load_terrain_dem
from satellite_coverage.engine.links import calculate_links
from satellite_coverage.engine.terrain_context import TerrainContext
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record
from satellite_coverage.orbit.visibility import parse_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem",type=Path,required=True)
    parser.add_argument("--geoid",type=Path,required=True)
    parser.add_argument("--tle",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run = RunRecord(args.output)
    try:
        evidence = json.loads((root / "reports/m3/copernicus-source.json").read_text())
        grid_evidence = json.loads((root / "reports/m3/egm2008-grid.json").read_text())
        declaration = {"sha256":evidence["local_sha256"],"height_unit":"m","vertical_datum":"EGM2008",
                       "surface_type":"DSM","evidence":evidence["source_assessment"]}
        geoid = {"path":str(args.geoid.resolve()),"sha256":grid_evidence["sha256"],"model":"EGM2008",
                 "evidence":"PROJ CDN https://cdn.proj.org/us_nga_egm08_25.tif; explicit local grid"}
        grid, metadata = load_terrain_dem(args.dem,declaration,lon_deg=108.9,lat_deg=34.24,
                                          radius_m=3000,resolution_m=60,geoid=geoid)
        run.write("source_evidence.json",evidence)
        run.write("geoid_evidence.json",grid_evidence)
        run.write("terrain.json",metadata)
        np.save(run.path/"terrain_ellipsoid_m.npy",grid.elevations_m,allow_pickle=False)
        ground, status = grid.sample(0,0)
        if status != "known":
            raise ValueError("receiver DSM elevation missing")
        config = yaml.safe_load((root/"configs/m1_tle.yaml").read_text())
        config["receiver"].update(antenna_ellipsoid_height_m=ground+2,
                                  basis="Assumed 2 m above converted DSM surface; not surveyed bare-ground AGL")
        config["step_s"] = 120  # bounded initial day-sequence integration
        raw = args.tle.read_bytes()
        (run.path/"input.tle").write_bytes(raw)
        catalog = parse_catalog(raw)
        run.write("config.json",config)
        run.write("environment.json",environment_record(root))
        archive_sources(root,run.path/"sources.zip")
        result = calculate_links(config,catalog,terrain=TerrainContext(grid,108.9,34.24,3000,60,6371000,60))
        baseline = calculate_links(config,catalog)
        run.write("links.json",result)
        run.write("free_space.json",baseline)
        known, errors = [], []
        for a,b in zip(result["records"],baseline["records"]):
            if a["budget"] and a["budget"]["received_power"]["status"] == "known":
                known.append(a)
                errors.append(abs(a["budget"]["received_power"]["value"]-
                                  (b["budget"]["received_power"]["value"]-a["terrain"]["used_loss_db"])))
        summary = {"samples":len(result["records"]),"known_terrain_power_samples":len(known),
                   "complete":result["complete"],"receiver_ellipsoid_height_m":ground+2,
                   "max_reassembly_error_db":max(errors) if errors else None,
                   "blocked_samples":sum(r.get("terrain",{}).get("los_status")=="blocked" for r in result["records"]),
                   "scope":"conditional local DSM experiment; 3 km radius, 60 m sampling, 120 s time step; not coverage truth"}
        run.write("summary.json",summary)
        passed = bool(known) and max(errors) <= 1e-6
        run.finish("passed" if passed and result["complete"] else "incomplete",**summary)
        print(json.dumps(summary,indent=2),flush=True)
        if not passed or not result["complete"]:
            raise SystemExit(2)
    except Exception as exc:
        run.finish("failed",reason=str(exc))
        raise


if __name__ == "__main__":
    main()
