"""Radius/step/height sweep at city, foothill and mountain DSM locations."""

import argparse
import json
from pathlib import Path

import numpy as np

from satellite_coverage.data_sources.terrain_dem import load_terrain_dem
from satellite_coverage.engine.terrain_link import evaluate_profile
from satellite_coverage.experiments.terrain_sensitivity import compare_profiles
from satellite_coverage.geometry.terrain import terrain_profile
from satellite_coverage.geometry.cell_horizon import cell_horizon
from satellite_coverage.geometry.cell_profile import cell_profile
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem",type=Path,required=True)
    parser.add_argument("--geoid",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--sampling-method",choices=("uniform","cell_intervals"),default="uniform")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    settings = {"sites":[{"id":"xian_city","lon":108.9,"lat":34.24},
                          {"id":"qinling_foothill","lon":108.9,"lat":34.05},
                          {"id":"qinling_mountain","lon":108.9,"lat":33.9}],
                "radii_m":[3000,6000,12000],"steps_m":[60,30,15,7.5],"grid_resolution_m":60,
                "heights_above_surface_m":[2,10],"azimuths_deg":list(range(0,360,5)),
                "query_elevations_deg":[1,5,10,30],"slant_range_m":550000,"frequency_hz":14.5e9,
                "effective_radius_m":6371000,"horizon_tolerance_deg":.1,"raw_loss_tolerance_db":1,
                "threshold_basis":"diagnostic engineering thresholds, not an accepted scientific accuracy requirement",
                "source_scope":"same 60 m nearest-cell DSM; finer ray steps do not increase native DEM truth resolution"}
    settings["sampling_method"] = args.sampling_method
    profile_builder = cell_profile if args.sampling_method == "cell_intervals" else terrain_profile
    run = RunRecord(args.output)
    try:
        evidence = json.loads((root/"reports/m3/copernicus-source.json").read_text())
        geoid_evidence = json.loads((root/"reports/m3/egm2008-grid.json").read_text())
        declaration = {"sha256":evidence["local_sha256"],"height_unit":"m","vertical_datum":"EGM2008",
                       "surface_type":"DSM","evidence":evidence["source_assessment"]}
        geoid = {"path":str(args.geoid.resolve()),"sha256":geoid_evidence["sha256"],"model":"EGM2008",
                 "evidence":geoid_evidence["url"]}
        run.write("config.json",settings)
        run.write("source_evidence.json",evidence)
        run.write("geoid_evidence.json",geoid_evidence)
        run.write("environment.json",environment_record(root))
        archive_sources(root,run.path/"sources.zip")
        summaries = []
        for site in settings["sites"]:
            grid, metadata = load_terrain_dem(args.dem,declaration,lon_deg=site["lon"],lat_deg=site["lat"],
                                              radius_m=12000,resolution_m=60,geoid=geoid)
            run.write(site["id"]+"-terrain.json",metadata)
            np.save(run.path/(site["id"]+"-ellipsoid.npy"),grid.elevations_m,allow_pickle=False)
            rows = []
            for radius in settings["radii_m"]:
                for step in settings["steps_m"]:
                    for height in settings["heights_above_surface_m"]:
                        for azimuth in settings["azimuths_deg"]:
                            profile = profile_builder(grid,receiver_east_m=0,receiver_north_m=0,antenna_agl_m=height,
                                                      azimuth_deg=azimuth,radius_m=radius,step_m=step,effective_radius_m=6371000)
                            queries = {}
                            for elevation in settings["query_elevations_deg"]:
                                result = evaluate_profile(profile,elevation_deg=elevation,slant_range_m=550000,frequency_hz=14.5e9)
                                queries[str(elevation)] = {k:result[k] for k in ("los_status","loss_status","raw_loss_db","cap_triggered")}
                            rows.append({"radius_m":radius,"step_m":step,"height_above_surface_m":height,"azimuth_deg":azimuth,
                                         "coverage_complete":profile["coverage_complete"],"horizon_deg":profile["horizon_deg"],
                                         "limiting_distance_m":profile["limiting_distance_m"],"queries":queries})
                    print(f"{site['id']}: radius={radius} step={step} done",flush=True)
            def select(radius,step):
                return [r for r in rows if r["radius_m"]==radius and r["step_m"]==step]
            step_comparisons = [{"radius_m":r,"step_m":s,"reference_step_m":7.5,
                                 **compare_profiles(select(r,s),select(r,7.5))}
                                for r in settings["radii_m"] for s in settings["steps_m"][:-1]]
            radius_comparisons = [{"radius_m":r,"reference_radius_m":12000,"step_m":7.5,
                                   **compare_profiles(select(r,7.5),select(12000,7.5))} for r in (3000,6000)]
            exact_rows = []
            for height in settings["heights_above_surface_m"]:
                for azimuth in settings["azimuths_deg"]:
                    exact_rows.append({"height_above_surface_m":height,"azimuth_deg":azimuth,
                                       **cell_horizon(grid,receiver_east_m=0,receiver_north_m=0,antenna_agl_m=height,
                                                      azimuth_deg=azimuth,radius_m=12000,effective_radius_m=6371000)})
            exact_map = {(r["height_above_surface_m"],r["azimuth_deg"]):r for r in exact_rows}
            exact_comparisons = []
            for step in settings["steps_m"]:
                errors = []
                unavailable = 0
                for row in select(12000,step):
                    ref = exact_map[(row["height_above_surface_m"],row["azimuth_deg"])]
                    if not row["coverage_complete"] or not ref["coverage_complete"]:
                        unavailable += 1
                        continue
                    errors.append(abs(row["horizon_deg"]-ref["horizon_deg"]))
                exact_comparisons.append({"step_m":step,"max_error_deg":max(errors) if errors else None,
                                          "p95_error_deg":float(np.percentile(errors,95)) if errors else None,
                                          "unavailable_pairs":unavailable})
            run.write(site["id"]+"-cell-horizons.json",exact_rows)
            summary = {"site":site,"profiles":len(rows),"step_comparisons":step_comparisons,
                       "radius_comparisons":radius_comparisons,"cell_horizon_comparisons":exact_comparisons,
                       "scope":"stability within this sampled experiment; no guarantee beyond 12 km or between azimuths"}
            run.write(site["id"]+"-samples.json",rows)
            summaries.append(summary)
        run.write("summary.json",summaries)
        run.finish("passed",meaning="sweep execution completed; numerical stability assessed separately in summary",
                   sites=len(summaries),profiles=sum(s["profiles"] for s in summaries))
        print(f"Sweep archived at {args.output}",flush=True)
    except Exception as exc:
        run.finish("failed",reason=str(exc))
        raise


if __name__ == "__main__":
    main()
