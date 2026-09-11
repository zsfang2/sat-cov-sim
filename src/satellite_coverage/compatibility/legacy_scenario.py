"""Legacy single-frame API implemented through the public engine boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..engine import CoverageResult, run_legacy_scenario


class CoverageScenario:
    """Preserve the original dict/YAML-driven single-frame interface."""

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @classmethod
    def from_yaml(cls, path: str | Path) -> "CoverageScenario":
        import yaml

        return cls(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def run(self) -> CoverageResult:
        return run_legacy_scenario(self.config)


__all__ = ["CoverageScenario", "CoverageResult"]
