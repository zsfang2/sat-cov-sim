#!/usr/bin/env bash
# Keep each process on its interpreter's bundled PROJ/GDAL databases.
set -euo pipefail
script_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
geo_python="${SATCOVER_PYTHON:-${script_root}/.venv/bin/python}"
if [[ ! -x "$geo_python" ]]; then
  echo "Python not found: $geo_python; create .venv or set SATCOVER_PYTHON." >&2
  exit 2
fi
# These are inherited foreign-library overrides, not project configuration.
# Removing them in the child lets the installed wheels select matching data.
exec env -u PROJ_DATA -u PROJ_LIB -u GDAL_DATA -u PYTHONPATH -u PYTHONHOME -u PYTHONUSERBASE \
  PYTHONNOUSERSITE=1 "$geo_python" "$@"
