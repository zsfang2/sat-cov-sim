"""Exercise real local TLE and DEM with an explicit, reproducible request."""

import argparse
import json
from pathlib import Path
import resource
import time

from satellite_coverage.data_sources.dem_preview import dem_info, dem_preview
from satellite_coverage.orbit.visibility import calculate_visibility, parse_catalog, satellite_track


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path("../Satellite-Ground-Radiomap"))
    parser.add_argument("--output", type=Path, default=Path("output/explorer-verification.json"))
    parser.add_argument("--all-satellites", action="store_true")
    parser.add_argument("--dem-overview-only", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    if args.dem_overview_only:
        path = args.source_root / "data/l2_topo/china_dem_30.tif"
        info = dem_info(path)
        tile = dem_preview(path, info["bounds_wgs84"])
        record = {k: v for k, v in tile.items() if k != "values"}
        record["elapsed_s"] = time.monotonic() - started
        record["peak_rss_kib_linux"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        print(f"Full DEM overview: {record['elapsed_s']:.2f}s; valid fraction {tile['valid_fraction']:.3f}; peak RSS {record['peak_rss_kib_linux']/1024:.1f} MiB; saved {args.output}", flush=True)
        return
    catalog = parse_catalog((args.source_root / "data/starlink-2025-tle/2025-01-01.tle").read_bytes())
    summary = catalog.summary()
    print({k: v for k, v in summary.items() if k != "items"}, flush=True)
    ids = None if args.all_satellites else sorted(catalog.records)[:20]
    request = {"start": "2025-01-01T00:00:00Z", "end": "2025-01-01T02:00:00Z",
               "min_elevation_deg": 10, "max_age_days": 7, "region_rule": "any",
               "satellite_ids": ids,
               "observer": {"mode": "point", "lat": 34.2427189, "lon": 108.9016839, "height_m": 0}}
    def progress(done, total, windows):
        if done % 250 == 0 or done == total:
            print(f"{done}/{total} satellites; {windows} windows; {time.monotonic()-started:.1f}s", flush=True)
    result = calculate_visibility(catalog, request, progress)
    region_ids = list(dict.fromkeys(w["norad_id"] for w in result["windows"]))[:20] or sorted(catalog.records)[:20]
    request = {**request, "satellite_ids": region_ids,
               "observer": {"mode": "region", "bounds": [108.8, 34.1, 109.0, 34.3], "grid": 3, "height_m": 0}}
    region = calculate_visibility(catalog, request)
    tile = dem_preview(args.source_root / "data/l2_topo/china_dem_30.tif", [108.65, 34.05, 109.15, 34.45])
    track = satellite_track(catalog, result["request"], result["windows"][0]["norad_id"]) if result["windows"] else None
    record = {"catalog": {k: v for k, v in summary.items() if k != "items"}, "point": result,
              "region_3x3_up_to_20_visible_satellites": region, "dem": {k: v for k, v in tile.items() if k != "values"},
              "track_samples": len(track["samples"]) if track else 0,
              "peak_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "elapsed_s": time.monotonic()-started}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(f"Saved {args.output}; {len(result['windows'])} point windows, {len(region['windows'])} region windows, DEM valid fraction {tile['valid_fraction']:.3f}", flush=True)


if __name__ == "__main__":
    main()
