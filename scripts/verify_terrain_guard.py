"""Replay archived real DSM/TLE inputs with the horizon sampling guard."""

import argparse
import json
from pathlib import Path
import shutil

import numpy as np

from satellite_coverage.data_sources.manifest import checksum_sha256
from satellite_coverage.engine.links import calculate_links
from satellite_coverage.engine.terrain_context import TerrainContext
from satellite_coverage.geometry.terrain import TerrainGrid
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record
from satellite_coverage.orbit.visibility import parse_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--sampling-method",choices=("uniform","cell_intervals"),default="uniform")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run = RunRecord(args.output)
    try:
        expected = json.loads((args.run/"artifacts.json").read_text())["files"]
        for name in ("terrain.json","terrain_ellipsoid_m.npy","config.json","input.tle"):
            if checksum_sha256(args.run/name) != expected[name]:
                raise ValueError(f"archive checksum mismatch: {name}")
            shutil.copyfile(args.run/name,run.path/name)
        metadata = json.loads((run.path/"terrain.json").read_text())
        values = np.load(run.path/"terrain_ellipsoid_m.npy",allow_pickle=False)
        config = json.loads((run.path/"config.json").read_text())
        resolution = metadata["resolution_m"]
        grid = TerrainGrid(values,-values.shape[1]*resolution/2,values.shape[0]*resolution/2,resolution,
                           "WGS84_ellipsoid","archived:"+expected["terrain_ellipsoid_m.npy"],surface_type="DSM")
        catalog = parse_catalog((run.path/"input.tle").read_bytes())
        run.write("replay.json",{"source_run":str(args.run),"verified_inputs":{n:expected[n] for n in
                                 ("terrain.json","terrain_ellipsoid_m.npy","config.json","input.tle")},
                                 "horizon_tolerance_deg":.1,"steps_m":[60,15,7.5],
                                 "sampling_method":args.sampling_method,
                                 "scope":"finite-radius sampling guard; not loss/radius accuracy certification"})
        run.write("environment.json",environment_record(root))
        archive_sources(root,run.path/"sources.zip")
        summaries = []
        for step in (60,15,7.5):
            terrain = TerrainContext(grid,metadata["lon_deg"],metadata["lat_deg"],3000,step,6371000,60,.1,args.sampling_method)
            result = calculate_links(config,catalog,terrain=terrain)
            audits = [r["terrain"]["sampling_audit"] for r in result["records"] if "sampling_audit" in r.get("terrain",{})]
            known = [r for r in result["records"] if r["budget"] and r["budget"]["received_power"]["status"]=="known"]
            summary = {"step_m":step,"samples":len(result["records"]),"audited_samples":len(audits),
                       "guard_failed_samples":sum(not a["passed"] for a in audits),"known_power_samples":len(known),
                       "max_horizon_error_deg":max(a["horizon_error_deg"] for a in audits if a["horizon_error_deg"] is not None),
                       "complete":result["complete"]}
            for row in result["records"]:
                audit = row.get("terrain",{}).get("sampling_audit")
                if audit and not audit["passed"] and row["budget"]["received_power"]["status"]=="known":
                    raise AssertionError("sampling guard leaked known power")
            run.write(f"links-step-{step}.json",result)
            summaries.append(summary)
        run.write("summary.json",summaries)
        run.finish("passed",meaning="guard behavior verified; link completeness is reported separately",comparisons=len(summaries))
        print(json.dumps(summaries,indent=2),flush=True)
    except Exception as exc:
        run.finish("failed",reason=str(exc))
        raise


if __name__ == "__main__":
    main()
