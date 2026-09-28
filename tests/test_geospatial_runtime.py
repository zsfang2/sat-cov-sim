import json
import os
from pathlib import Path
import subprocess
import sys


def test_launcher_isolates_foreign_databases_and_reprojects(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.update(SATCOVER_PYTHON=sys.executable, PROJ_DATA=str(tmp_path / "wrong-proj"),
               PROJ_LIB=str(tmp_path / "wrong-proj-lib"), GDAL_DATA=str(tmp_path / "wrong-gdal"))
    output = tmp_path / "check.json"
    run = subprocess.run(["bash", str(root / "scripts/python_geo.sh"),
                          str(root / "scripts/check_geo_environment.py"), str(output)],
                         env=env, cwd=root, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    result = json.loads(output.read_text())
    assert result["status"] == "passed"
    assert result["reprojection_valid_pixels"] > 0
    assert all(value is None for value in result["foreign_data_overrides"].values())
