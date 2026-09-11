"""Public orchestration entry points with no import-time data access."""

from .api import CoverageResult, run_legacy_scenario

__all__ = ["CoverageResult", "run_legacy_scenario"]
