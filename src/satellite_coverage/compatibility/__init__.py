"""Compatibility APIs retained while callers migrate to the simulation engine."""

from .legacy_scenario import CoverageResult, CoverageScenario

__all__ = ["CoverageScenario", "CoverageResult"]
