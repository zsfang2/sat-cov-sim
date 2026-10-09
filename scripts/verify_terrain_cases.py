"""Small deterministic domain matrix with expectations fixed before evaluation."""

import argparse
from pathlib import Path

import numpy as np

from satellite_coverage.config.pilot import identity
from satellite_coverage.engine.terrain_context import TerrainContext
from satellite_coverage.engine.terrain_link import evaluate_profile
from satellite_coverage.geometry.cell_profile import cell_profile
from satellite_coverage.geometry.terrain import TerrainGrid
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run = RunRecord(args.output)
    cases = [
        dict(id="flat-horizontal", elevation=0, loss="known", los="clear_within_radius"),
        dict(id="flat-low", elevation=1e-12, loss="known", los="clear_within_radius"),
        dict(id="flat-high", elevation=89.9, loss="known", los="clear_within_radius", raw=0),
        dict(id="near-zenith", elevation=89.999, loss="not_computed", reason="satellite_within_profile_radius; shorten_profile"),
        dict(id="near-transmitter", range=100, loss="not_computed", reason="satellite_within_profile_radius; shorten_profile"),
        dict(id="radius-equality", range=150, elevation=0, loss="not_computed", reason="satellite_within_profile_radius; shorten_profile"),
        dict(id="ridge", terrain="ridge", loss="known", los="blocked", cap=3, capped=True),
        dict(id="double-ridge", terrain="double", loss="known", los="blocked"),
        dict(id="shifted-ridge", terrain="ridge", shift=500, loss="known", los="blocked"),
        dict(id="raised-antenna", terrain="ridge", height=202, loss="known", los="clear_within_radius", raw=0),
        dict(id="ray-nodata", terrain="gap", loss="not_computed", reason="nodata"),
        dict(id="receiver-nodata", terrain="receiver-gap", loss="not_computed", reason="receiver_nodata"),
        dict(id="outside", radius=300, loss="not_computed", reason="outside_dem"),
        dict(id="tiny-frequency", frequency=1e-320, error="finite numerical range"),
        dict(id="height-overflow", terrain="overflow", error="finite numerical range"),
        dict(id="zenith", zenith=True, loss="not_computed", reason="zenith_profile_not_supported"),
    ]
    try:
        run.write("config.json", cases)
        run.write("environment.json", environment_record(root))
        archive_sources(root,run.path/"sources.zip")
        rows = []
        for case in cases:
            values = np.zeros((41,41))
            terrain = case.get("terrain")
            if terrain in ("ridge","double"):
                values[10,:] = 102
            if terrain == "double":
                values[7,:] = 130
            if terrain == "gap":
                values[10,20] = np.nan
            if terrain == "receiver-gap":
                values[20,20] = np.nan
            if terrain == "overflow":
                values[:] = -1e308; values[10,:] = 1e308
            values += case.get("shift",0)
            grid = TerrainGrid(values,-205,205,10,"WGS84_ellipsoid",identity(case),surface_type="synthetic")
            np.save(run.path/(case["id"]+".npy"),values,allow_pickle=False)
            try:
                if case.get("zenith"):
                    result = TerrainContext(grid,0,0,150,10,sampling_method="cell_intervals").evaluate(
                        dict(geometrically_above_local_horizontal=True,azimuth_deg=None),dict(antenna_ellipsoid_height_m=2))
                else:
                    p = cell_profile(grid,receiver_east_m=0,receiver_north_m=0,antenna_agl_m=case.get("height",2),
                                     azimuth_deg=0,radius_m=case.get("radius",150),step_m=10)
                    result = evaluate_profile(p,elevation_deg=case.get("elevation",30),slant_range_m=case.get("range",550000),
                                              frequency_hz=case.get("frequency",14.5e9),loss_cap_db=case.get("cap",60))
                if "error" in case:
                    raise AssertionError("expected numerical refusal")
                assert result["loss_status"] == case["loss"]
                for key, actual in (("los","los_status"),("raw","raw_loss_db"),("capped","cap_triggered")):
                    if key in case:
                        assert result[actual] == case[key]
                if "reason" in case:
                    assert case["reason"] in result.get("incomplete_reasons",[result.get("reason")])
                rows.append(dict(case=case,input_id=identity(case),passed=True,result=result))
            except ValueError as exc:
                if "error" not in case or case["error"] not in str(exc):
                    raise
                rows.append(dict(case=case,input_id=identity(case),passed=True,error=str(exc)))
        a = next(r for r in rows if r["case"]["id"] == "ridge")["result"]
        b = next(r for r in rows if r["case"]["id"] == "shifted-ridge")["result"]
        assert a["raw_loss_db"] == b["raw_loss_db"]
        run.write("cases.json",rows)
        run.finish("passed",cases=len(rows),common_datum_raw_loss_invariant=True)
        print(f"{len(rows)} cases passed: {args.output}")
    except Exception as exc:
        run.finish("failed",reason=str(exc))
        raise


if __name__ == "__main__":
    main()
