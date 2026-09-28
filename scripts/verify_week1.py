"""Recreate the scoped acceptance evidence; never upgrades reference status."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New acceptance directory")
    parser.add_argument("--source-root", required=True, help="Existing external source repository")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    stages = []

    def call(name, command):
        result = subprocess.run(command, cwd=root, capture_output=True, text=True)
        (output / (name + ".txt")).write_text(result.stdout + result.stderr)
        stages.append({"name": name, "command": command, "returncode": result.returncode})
        if result.returncode:
            raise RuntimeError(f"{name} failed; see {output / (name + '.txt')}")

    try:
        call("environment", [sys.executable, str(root / "scripts/check_geo_environment.py"), str(output / "geo-environment.json")])
        call("dependencies", [sys.executable, "-m", "pip", "check"])
        call("tests", [sys.executable, "-m", "pytest", "tests", "-q"])
        base = [sys.executable, "-m", "satellite_coverage.experiments.pilot"]
        call("audit", base + ["validate-data", "--config", "configs/pilot.yaml", "--source-root", str(Path(args.source_root).resolve()),
                              "--output", str(output / "audit")])
        for name in ("run-a", "run-b"):
            call(name, base + ["run", "--config", "configs/pilot.yaml", "--output", str(output / name)])
        deterministic = ["config.json", "inputs.json", "link_records.json", "source_snapshot.zip"]
        comparisons = {name: (output / "run-a" / name).read_bytes() == (output / "run-b" / name).read_bytes()
                       for name in deterministic}
        if not all(comparisons.values()):
            raise RuntimeError("same-environment deterministic results differ")
        checksums = {}
        for name in ("audit", "run-a", "run-b"):
            folder = output / name
            entries = read(folder / "artifacts.json")["files"]
            checksums[name] = all("sha256:" + hashlib.sha256((folder / filename).read_bytes()).hexdigest() == digest
                                  for filename, digest in entries.items())
        if not all(checksums.values()):
            raise RuntimeError("output checksum mismatch")
        audit = read(output / "audit/sample-audit.json")
        # An unknown vertical datum is a recorded audit finding, not a silently
        # satisfied physical prerequisite. This is an explicit scope distinction.
        report = {"status": "passed_for_week1_scope", "tests": (output / "tests.txt").read_text().strip(),
                  "stages": stages, "deterministic_comparisons": comparisons, "artifact_checks": checksums,
                  "source_identity": read(output / "run-a/environment.json")["source_fingerprint"],
                  "scope": "analytic scalar link and real sample audit; no terrain-reference certification",
                  "unresolved_data_findings": audit["limitations"], "reference_ready": False}
        for source, target in (("audit/sample-audit.json", "sample-audit.json"), ("run-a/environment.json", "environment.json"),
                               ("run-a/link_records.json", "link_records.json")):
            shutil.copyfile(output / source, output / target)
    except Exception as exc:
        (output / "acceptance.json").write_text(json.dumps({"status": "failed", "stages": stages, "reason": str(exc)}, indent=2) + "\n")
        raise
    (output / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
