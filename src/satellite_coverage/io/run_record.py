"""Exclusive run directories, source fingerprints and atomic JSON records."""

from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
import zipfile

from ..config.pilot import identity
from ..data_sources.manifest import checksum_sha256


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def source_files(project_root):
    root = Path(project_root)
    files = [root / "pyproject.toml"]
    for folder, pattern in (("src", "*.py"), ("tests", "*.py"), ("tests/fixtures", "*.json"),
                            ("scripts", "*.py"), ("scripts", "*.sh"), ("configs", "*.yaml"),
                            ("data_manifest", "*.yaml")):
        files.extend((root / folder).rglob(pattern))
    files.extend(root.glob("requirements-week1.*"))
    return sorted(set(p for p in files if p.is_file()))


def archive_sources(project_root, destination):
    """Archive the exact small source/config set, including uncommitted files."""
    root = Path(project_root)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in source_files(root):
            info = zipfile.ZipInfo(str(path.relative_to(root)), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())


def environment_record(project_root):
    root = Path(project_root)
    def git(*args):
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
        return p.stdout.strip() if p.returncode == 0 else None
    files = source_files(root)
    hashes = {str(p.relative_to(root)): checksum_sha256(p) for p in files if p.is_file()}
    packages = {}
    for name in ("numpy", "PyYAML", "rasterio", "pyproj", "skyfield", "geopandas", "pytest", "satellite-coverage-sim"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    status = git("status", "--porcelain")
    cpu_model = platform.processor()
    cpu_info = Path("/proc/cpuinfo")
    if cpu_info.exists():
        cpu_model = next((line.split(":", 1)[1].strip() for line in cpu_info.read_text().splitlines()
                          if line.startswith("model name")), cpu_model)
    native = {}
    try:
        import rasterio
        import pyproj
        native = {"gdal": rasterio.__gdal_version__, "proj": pyproj.proj_version_str,
                  "pyproj_data_dir": pyproj.datadir.get_data_dir(),
                  "rasterio_proj_data_dir": str(Path(rasterio.__file__).parent / "proj_data")}
    except ImportError:
        pass
    return {
        "python": sys.version, "executable": sys.executable, "platform": platform.platform(),
        "sys_prefix": sys.prefix, "sys_base_prefix": sys.base_prefix,
        "isolated_venv": sys.prefix != sys.base_prefix,
        "packages": packages, "native_libraries": native,
        "installed_distributions": dict(sorted((dist.metadata["Name"], dist.version)
                                               for dist in importlib.metadata.distributions()
                                               if dist.metadata["Name"])),
        "geospatial_data_environment": {name: os.environ.get(name) for name in ("PROJ_DATA", "PROJ_LIB", "GDAL_DATA")},
        "code_commit": git("rev-parse", "HEAD"), "dirty": bool(status) if status is not None else None,
        "git_status": status, "source_files": hashes, "source_fingerprint": identity(hashes),
        "cpu_model": cpu_model, "cpu_count": os.cpu_count(),
        "thread_environment": {name: os.environ.get(name) for name in
                               ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "GDAL_NUM_THREADS")},
        "peak_rss_unit": "KiB on Linux, bytes on macOS",
    }


class RunRecord:
    def __init__(self, output):
        self.path = Path(output)
        self.path.mkdir(parents=True, exist_ok=False)
        self.started = time.perf_counter()
        self.write_seconds = 0.0
        self.write("validation.json", {"status": "running"})
        self.log("run_started")

    def write(self, name, value):
        start = time.perf_counter()
        write_json(self.path / name, value)
        self.write_seconds += time.perf_counter() - start

    def log(self, message):
        with (self.path / "run.log").open("a", encoding="utf-8") as stream:
            stream.write(datetime.now(timezone.utc).isoformat() + " " + message + "\n")

    def finish(self, status, **details):
        self.log("run_" + status)
        self.write("validation.json", {"status": status, **details})
        self.write("resources.json", {"wall_time_s": time.perf_counter() - self.started,
                                      "json_write_time_s_before_resource_record": self.write_seconds,
                                      "peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
        files = {p.name: checksum_sha256(p) for p in self.path.iterdir() if p.is_file() and p.name != "artifacts.json"}
        self.write("artifacts.json", {"schema_version": 1, "files": files})
