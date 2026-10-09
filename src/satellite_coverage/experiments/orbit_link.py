"""Reproducible M1 fixed/direction/TLE experiment; no browser required."""

import argparse
import hashlib
from pathlib import Path

import yaml

from ..engine.orbit_link import calculate_orbit_links
from ..engine.links import calculate_links
from ..io.run_record import RunRecord, archive_sources, environment_record
from ..orbit.visibility import parse_catalog
from ..config.pilot import exact_keys
from ..data_sources.terrain_tiles import TerrainReadBudget, TerrainResourceError


def execute(config_path, tle_path, output, project_root, terrain_path=None):
    run = RunRecord(output)
    try:
        config_raw = Path(config_path).read_text(encoding="utf-8")
        data = yaml.safe_load(config_raw)
        run.write("config.json", data)
        run.write("config_source.json", {"path": str(config_path), "text": config_raw})
        run.write("environment.json", environment_record(project_root))
        archive_sources(project_root, run.path / "sources.zip")
        uses_tle = "source" not in data or data["source"].get("mode") == "tle"
        catalog = None
        if uses_tle:
            if tle_path is None:
                raise ValueError("TLE mode requires --tle")
            raw = Path(tle_path).read_bytes()
            (run.path / "input.tle").write_bytes(raw)
            run.write("inputs.json", {"tle_path": str(tle_path), "tle_sha256": hashlib.sha256(raw).hexdigest()})
            catalog = parse_catalog(raw)
        else:
            if tle_path is not None:
                raise ValueError("--tle only applies to TLE sources")
            run.write("inputs.json", {"source": data["source"]})
        terrain = None
        if terrain_path is not None:
            import numpy as np
            from ..data_sources.terrain_dem import load_terrain_dem
            from ..engine.terrain_context import TerrainContext
            if "source" not in data:
                raise ValueError("terrain requires the unified M1 config")
            terrain_path = Path(terrain_path).resolve()
            terrain_text = terrain_path.read_text(encoding="utf-8")
            options = yaml.safe_load(terrain_text)
            required = {"dem_path", "declaration", "geoid", "radius_m", "resolution_m",
                        "step_m", "effective_radius_m", "loss_cap_db"}
            if not isinstance(options, dict):
                raise ValueError('terrain config must be a mapping')
            optional = {"horizon_tolerance_deg", "sampling_method", "read_budget"} & options.keys()
            exact_keys(options, required | optional, "terrain config")
            dem_path = (terrain_path.parent / options["dem_path"]).resolve()
            geoid = options["geoid"]
            if geoid is not None:
                geoid = {**geoid, "path": str((terrain_path.parent / geoid["path"]).resolve())}
            run.write("terrain_source.json", {"path": str(terrain_path), "text": terrain_text})
            budget_options = options.get('read_budget', {})
            if not isinstance(budget_options, dict) or set(budget_options)-set(TerrainReadBudget.__dataclass_fields__):
                raise ValueError('invalid terrain read_budget mapping')
            diagnostics = {}
            grid, metadata = load_terrain_dem(dem_path, options["declaration"],
                                              lon_deg=data["receiver"]["lon_deg"], lat_deg=data["receiver"]["lat_deg"],
                                              radius_m=options["radius_m"], resolution_m=options["resolution_m"], geoid=geoid,
                                              read_budget=TerrainReadBudget(**budget_options), diagnostics=diagnostics)
            run.write('terrain_read.json', diagnostics)
            terrain = TerrainContext(grid, data["receiver"]["lon_deg"], data["receiver"]["lat_deg"],
                                     options["radius_m"], options["step_m"], options["effective_radius_m"], options["loss_cap_db"],
                                     options.get("horizon_tolerance_deg"), options.get("sampling_method", "uniform"))
            run.write("terrain.json", metadata)
            np.save(run.path / "terrain_ellipsoid_m.npy", grid.elevations_m, allow_pickle=False)
        result = calculate_links(data, catalog, terrain=terrain) if "source" in data else calculate_orbit_links(catalog, data)
        run.write("links.json", result)
        known = [r["budget"]["received_power"]["value"] for r in result["records"]
                 if r["budget"] and r["budget"]["received_power"]["status"] == "known"]
        run.finish("passed" if result["complete"] else "incomplete",
                   samples=len(result["records"]), known_power_samples=len(known),
                   min_power_dbm=min(known) if known else None, max_power_dbm=max(known) if known else None,
                   meaning="execution validation only, not physical truth certification")
        return result
    except Exception as exc:
        kind = ('resource_budget_exceeded' if isinstance(exc,TerrainResourceError) else
                'invalid_input' if isinstance(exc,(ValueError,TypeError,KeyError,yaml.YAMLError)) else
                'upstream_unavailable' if isinstance(exc,OSError) else 'solver_failure')
        run.finish("failed", reason=str(exc), failure_kind=kind)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tle", type=Path, help="required for TLE mode only")
    parser.add_argument("--terrain", type=Path, help="optional declared DEM, geoid and profile configuration")
    parser.add_argument("--output", type=Path, required=True, help="new exclusive directory")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[3])
    args = parser.parse_args()
    result = execute(args.config, args.tle, args.output, args.project_root, args.terrain)
    print(f"{args.output}: {len(result['records'])} samples; complete={result['complete']}")
    if not result["complete"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
