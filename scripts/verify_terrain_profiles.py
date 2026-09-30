"""Reproduce controlled M3 profile cases without external DEM assumptions."""

import argparse
from pathlib import Path

import numpy as np

from satellite_coverage.geometry.terrain import TerrainGrid, terrain_profile
from satellite_coverage.engine.terrain_link import evaluate_profile
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run = RunRecord(args.output)
    try:
        run.write("environment.json", environment_record(root))
        archive_sources(root, run.path / "sources.zip")
        cases = []
        for name in ("flat", "ridge", "nodata", "insufficient_extent"):
            heights = np.zeros((41, 41))
            if name == "ridge":
                heights[10, :] = 102
            if name == "nodata":
                heights[10, 20] = np.nan
            dem = TerrainGrid(heights, -205, 205, 10, "synthetic metre datum", name)
            profile = terrain_profile(dem, receiver_east_m=0, receiver_north_m=0, antenna_agl_m=2,
                                      azimuth_deg=0, radius_m=300 if name == "insufficient_extent" else 150,
                                      step_m=10)
            result = evaluate_profile(profile, elevation_deg=30, slant_range_m=550000,
                                      frequency_hz=14.5e9, loss_cap_db=20)
            cases.append({"name": name, "profile": profile, "result": result})
        run.write("cases.json", cases)
        expected = ["clear_within_radius", "blocked", "unknown", "unknown"]
        passed = [c["result"]["los_status"] for c in cases] == expected
        known = [c for c in cases if c["result"]["loss_status"] == "known"]
        run.finish("passed" if passed else "failed", case_count=len(cases), known_loss_cases=len(known),
                   capped_fraction_of_known=sum(c["result"]["cap_triggered"] for c in known)/len(known) if known else None,
                   scope="controlled local DEM profiles; not real terrain validation")
        if not passed:
            raise SystemExit(1)
        print(f"{args.output}: 4 controlled terrain cases passed")
    except Exception as exc:
        run.finish("failed", reason=str(exc))
        raise


if __name__ == "__main__":
    main()
