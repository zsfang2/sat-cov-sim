from __future__ import annotations

import ast
import importlib
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"
SIMULATION_ROOT = SOURCE_ROOT / "satellite_coverage"
PUBLIC_MODULES = (
    "satellite_coverage.config",
    "satellite_coverage.domain",
    "satellite_coverage.data_sources",
    "satellite_coverage.orbit",
    "satellite_coverage.geometry",
    "satellite_coverage.scheduling",
    "satellite_coverage.propagation",
    "satellite_coverage.engine",
    "satellite_coverage.io",
    "satellite_coverage.compatibility",
    "satrm_benchmark",
)


@pytest.mark.parametrize("module_name", PUBLIC_MODULES)
def test_public_boundary_imports_in_fresh_interpreter(module_name: str):
    code = (
        "import importlib, sys; "
        f"sys.path.insert(0, {str(SOURCE_ROOT)!r}); "
        f"importlib.import_module({module_name!r})"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_simulation_package_does_not_import_benchmark_or_ml_internals():
    forbidden_roots = {"satrm_benchmark", "sklearn", "tensorflow", "torch"}

    for source_path in SIMULATION_ROOT.rglob("*.py"):
        imported_roots = {
            name.split(".", 1)[0]
            for name in _imported_names(source_path)
            if not name.startswith(".")
        }
        assert imported_roots.isdisjoint(forbidden_roots), source_path


def test_root_package_import_does_not_eagerly_load_legacy_runner():
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(SOURCE_ROOT)!r}); "
        "import satellite_coverage; "
        "assert 'satellite_coverage.scenario' not in sys.modules; "
        "assert 'satellite_coverage.engine._legacy' not in sys.modules"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_compatibility_import_does_not_load_legacy_runner_or_yaml():
    code = (
        "import importlib, sys; "
        f"sys.path.insert(0, {str(SOURCE_ROOT)!r}); "
        "importlib.import_module('satellite_coverage.compatibility'); "
        "assert 'satellite_coverage.engine._legacy' not in sys.modules; "
        "assert 'yaml' not in sys.modules"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_compatibility_facade_only_reaches_legacy_physics_through_engine_api():
    module = importlib.import_module("satellite_coverage.compatibility.legacy_scenario")
    imported_names = _imported_names(Path(module.__file__))

    assert "..engine" in imported_names
    assert not imported_names.intersection(
        {
            "..coordinates",
            "..geodata",
            "..propagation",
            "..tle",
        }
    )


def test_stable_scenario_module_exports_compatibility_facade():
    public_module = importlib.import_module("satellite_coverage.scenario")
    compatibility_module = importlib.import_module(
        "satellite_coverage.compatibility.legacy_scenario"
    )

    assert public_module.CoverageScenario is compatibility_module.CoverageScenario
    assert public_module.CoverageResult is compatibility_module.CoverageResult


def test_propagation_boundary_does_not_read_config_sources_or_outputs():
    forbidden = {
        ".config",
        ".data_sources",
        ".geodata",
        ".io",
        ".tle",
        "yaml",
    }

    imported_names = _imported_names(SIMULATION_ROOT / "propagation.py")

    assert not imported_names.intersection(forbidden)


def test_scheduler_boundary_does_not_import_propagation_or_engine():
    scheduler_root = SIMULATION_ROOT / "scheduling"
    forbidden = {"..engine", "..propagation"}

    for source_path in scheduler_root.rglob("*.py"):
        assert not _imported_names(source_path).intersection(forbidden), source_path


def test_benchmark_can_only_depend_on_public_dataset_io():
    benchmark_root = SOURCE_ROOT / "satrm_benchmark"

    for source_path in benchmark_root.rglob("*.py"):
        simulation_imports = {
            name
            for name in _imported_names(source_path)
            if name == "satellite_coverage" or name.startswith("satellite_coverage.")
        }
        assert all(
            name == "satellite_coverage.io"
            or name.startswith("satellite_coverage.io.")
            for name in simulation_imports
        ), source_path


def _imported_names(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            names.add(prefix + (node.module or ""))
    return names
