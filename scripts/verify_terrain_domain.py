"""Archive native/local-grid, sampling and curvature effects separately."""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import rasterio

from satellite_coverage.data_sources.terrain_dem import load_terrain_dem
from satellite_coverage.engine.terrain_link import evaluate_profile
from satellite_coverage.experiments.native_terrain import native_heights, sampled_profile
from satellite_coverage.geometry.cell_profile import cell_profile
from satellite_coverage.geometry.terrain import terrain_profile
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record


def comparison(left, right):
    def key(row):
        return row["height_m"], row["azimuth_deg"], row["elevation_deg"]
    a, b = {key(r): r for r in left}, {key(r): r for r in right}
    if set(a) != set(b) or len(a) != len(left) or len(b) != len(right):
        raise ValueError("diagnostic pairs must have identical unique query IDs")
    horizon, losses, heights = [], [], []
    changes = missing = 0
    for k, x in a.items():
        y = b[k]
        if x["horizon_deg"] is not None and y["horizon_deg"] is not None:
            horizon.append(abs(x["horizon_deg"]-y["horizon_deg"]))
        if x["raw_loss_db"] is not None and y["raw_loss_db"] is not None:
            losses.append(abs(x["raw_loss_db"]-y["raw_loss_db"]))
        else:
            missing += 1
        changes += x["los_status"] != y["los_status"] or x["loss_status"] != y["loss_status"]
        if x.get("point_height_max_delta_m") is not None:
            heights.append(x["point_height_max_delta_m"])
    return dict(pairs=len(a), known_loss_pairs=len(losses), unavailable_pairs=missing,
                state_disagreements=changes, max_horizon_delta_deg=max(horizon, default=None),
                max_raw_loss_delta_db=max(losses, default=None),
                max_point_height_delta_m=max(heights, default=None),
                horizon_over_0_1_deg=sum(v > .1 for v in horizon),
                loss_over_1_db=sum(v > 1 for v in losses))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem", type=Path, required=True)
    parser.add_argument("--geoid", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    radius, earth = 12000., 6371000.
    sites = [("xian_city",108.9,34.24), ("qinling_foothill",108.9,34.05), ("qinling_mountain",108.9,33.9)]
    settings = dict(radius_m=radius, grid_resolutions_m=[32,40,60], steps_m=[30,15,7.5],
                    heights_m=[2,10], azimuths_deg=list(range(0,360,15)), elevations_deg=[0,1,5,30,80],
                    range_m=550000, frequency_hz=14.5e9, effective_radii_m=[None,earth,4*earth/3],
                    sites=sites, diagnostic_thresholds=dict(horizon_deg=.1, raw_loss_db=1),
                    scope="sampled native-cell comparison and model sensitivity; not physical truth or business acceptance")
    run = RunRecord(args.output)
    try:
        evidence = json.loads((root/"reports/m3/copernicus-source.json").read_text())
        geoid_evidence = json.loads((root/"reports/m3/egm2008-grid.json").read_text())
        declaration = dict(sha256=evidence["local_sha256"], height_unit="m", vertical_datum="EGM2008",
                           surface_type="DSM", evidence=evidence["source_assessment"])
        geoid = dict(path=str(args.geoid.resolve()), sha256=geoid_evidence["sha256"], model="EGM2008",
                     evidence=geoid_evidence["url"])
        run.write("config.json", settings)
        run.write("source_evidence.json", evidence)
        run.write("geoid_evidence.json", geoid_evidence)
        run.write("environment.json", environment_record(root))
        archive_sources(root, run.path/"sources.zip")
        summaries = []
        for site, lon, lat in sites:
            grids = {}
            for resolution in settings["grid_resolutions_m"]:
                diagnostic = {}
                grid, meta = load_terrain_dem(args.dem, declaration, lon_deg=lon, lat_deg=lat,
                                              radius_m=radius, resolution_m=resolution, geoid=geoid,
                                              diagnostics=diagnostic)
                grids[resolution] = grid
                run.write(f"{site}-{resolution}-terrain.json",meta)
                run.write(f"{site}-{resolution}-read.json",diagnostic)
                np.save(run.path/f"{site}-{resolution}-grid.npy",grid.elevations_m,allow_pickle=False)
            rows = []
            with rasterio.Env(GDAL_CACHEMAX=32*1024**2), rasterio.open(args.dem) as src:
                ground_values, ground_status = native_heights(src,meta,[0],[0])
                ground = float(ground_values[0]) if ground_status == ["known"] else None
                for az in settings["azimuths_deg"]:
                    rays = {}
                    for step in settings["steps_m"]:
                        d = np.arange(1, int(radius/step)+1)*step
                        h, status = native_heights(src,meta,d*np.sin(np.deg2rad(az)),d*np.cos(np.deg2rad(az)))
                        rays[step] = (d,h,status)
                    for height in settings["heights_m"]:
                        profiles = []
                        for step, (d,h,status) in rays.items():
                            p = sampled_profile(d,h,status,ground=ground,agl=height,radius=radius,
                                                step=step,azimuth=az,effective_radius=earth)
                            profiles.append((f"native-{step:g}",p,None))
                        for resolution, grid in grids.items():
                            for step in (settings["steps_m"] if resolution == 60 else [15]):
                                for mode, builder in (("uniform",terrain_profile),("interval",cell_profile)):
                                    p = builder(grid,receiver_east_m=0,receiver_north_m=0,antenna_agl_m=height,
                                                azimuth_deg=az,radius_m=radius,step_m=step,effective_radius_m=earth)
                                    delta = None
                                    if mode == "uniform":
                                        native_h = rays[step][1]
                                        local_h = np.array([s["elevation_m"] if s["elevation_m"] is not None else np.nan
                                                            for s in p["samples"]])
                                        finite = np.isfinite(local_h) & np.isfinite(native_h)
                                        delta = float(np.abs(local_h[finite]-native_h[finite]).max()) if finite.any() else None
                                    profiles.append((f"local-{resolution}-{mode}-{step:g}",p,delta))
                        grid = grids[60]
                        for curvature in (None,4*earth/3):
                            p = cell_profile(grid,receiver_east_m=0,receiver_north_m=0,antenna_agl_m=height,
                                             azimuth_deg=az,radius_m=radius,step_m=15,effective_radius_m=curvature)
                            profiles.append(("curvature-none" if curvature is None else "curvature-4R3",p,None))
                        # Spherical and quadratic evaluated at identical local-raster samples.
                        d = rays[15][0]
                        local = [grid.sample(float(x*math.sin(math.radians(az))),float(x*math.cos(math.radians(az)))) for x in d]
                        p = sampled_profile(d,[h for h,_ in local],[s for _,s in local],ground=ground,agl=height,
                                            radius=radius,step=15,azimuth=az,effective_radius=earth,spherical=True)
                        profiles.append(("local-60-spherical-15",p,None))
                        for variant, p, delta in profiles:
                            for el in settings["elevations_deg"]:
                                result = evaluate_profile(p,elevation_deg=el,slant_range_m=550000,frequency_hz=14.5e9)
                                rows.append(dict(variant=variant,height_m=height,azimuth_deg=az,elevation_deg=el,
                                                 horizon_deg=p["horizon_deg"],point_height_max_delta_m=delta,
                                                 **{k:result[k] for k in ("los_status","loss_status","raw_loss_db","used_loss_db",
                                                                        "cap_triggered","incomplete_reasons")}))
            def select(variant):
                return [r for r in rows if r["variant"] == variant]
            pairs = []
            for resolution in settings["grid_resolutions_m"]:
                pairs.append(("native_to_local",f"local-{resolution}-uniform-15","native-15"))
            for step in (30,15):
                pairs.append(("native_sampling",f"native-{step}","native-7.5"))
                for mode in ("uniform","interval"):
                    pairs.append(("local_sampling",f"local-60-{mode}-{step}",f"local-60-{mode}-7.5"))
            pairs.extend([("local_resolution",f"local-{r}-interval-15","local-32-interval-15") for r in (40,60)])
            pairs.extend([("curvature",v,"local-60-interval-15") for v in ("curvature-none","curvature-4R3")])
            pairs.append(("spherical_geometry","local-60-spherical-15","local-60-uniform-15"))
            variants = {}
            for variant in sorted({r["variant"] for r in rows}):
                selected = select(variant)
                reasons = {}
                for row in selected:
                    for reason in row["incomplete_reasons"]:
                        reasons[reason] = reasons.get(reason,0)+1
                known = sum(r["loss_status"] == "known" for r in selected)
                variants[variant] = dict(queries=len(selected),known_loss=known,
                                          unknown_loss=len(selected)-known,capped=sum(r["cap_triggered"] for r in selected),
                                          cap_denominator=known,incomplete_reasons=reasons)
            summary = dict(site=site,queries=len(rows),variants=variants,
                           comparisons=[dict(factor=f,left=a,right=b,**comparison(select(a),select(b))) for f,a,b in pairs])
            run.write(f"{site}-queries.json", rows)
            summaries.append(summary)
            print(f"{site}: {len(rows)} queries",flush=True)
        # Explicit approximation differences over the whole admitted radius domain.
        curves = []
        for r in (1e6,earth,4*earth/3):
            for d in (3000.,12000.,24000.,48000.,100000.):
                curves.append(dict(radius_m=d,effective_radius_m=r,
                                   vertical_drop_delta_m=d*d/(2*r)-2*r*math.sin(d/(2*r))**2,
                                   horizontal_delta_m=d-r*math.sin(d/r)))
        run.write("curvature-geometry.json",curves)
        run.write("summary.json",summaries)
        run.finish("passed",meaning="diagnostic matrix executed; differences are not accuracy certification",
                   queries=sum(s["queries"] for s in summaries))
        print(args.output,flush=True)
    except Exception as exc:
        run.finish("failed",reason=str(exc))
        raise


if __name__ == "__main__":
    main()
