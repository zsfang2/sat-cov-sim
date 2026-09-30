"""Reproducible M1 fixed/direction/TLE experiment; no browser required."""

import argparse
import hashlib
from pathlib import Path

import yaml

from ..engine.orbit_link import calculate_orbit_links
from ..engine.links import calculate_links
from ..io.run_record import RunRecord, archive_sources, environment_record
from ..orbit.visibility import parse_catalog


def execute(config_path, tle_path, output, project_root):
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
        result = calculate_links(data, catalog) if "source" in data else calculate_orbit_links(catalog, data)
        run.write("links.json", result)
        known = [r["budget"]["received_power"]["value"] for r in result["records"]
                 if r["budget"] and r["budget"]["received_power"]["status"] == "known"]
        run.finish("passed" if result["complete"] else "incomplete",
                   samples=len(result["records"]), known_power_samples=len(known),
                   min_power_dbm=min(known) if known else None, max_power_dbm=max(known) if known else None,
                   meaning="execution validation only, not physical truth certification")
        return result
    except Exception as exc:
        run.finish("failed", reason=str(exc))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tle", type=Path, help="required for TLE mode only")
    parser.add_argument("--output", type=Path, required=True, help="new exclusive directory")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[3])
    args = parser.parse_args()
    result = execute(args.config, args.tle, args.output, args.project_root)
    print(f"{args.output}: {len(result['records'])} samples; complete={result['complete']}")
    if not result["complete"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
