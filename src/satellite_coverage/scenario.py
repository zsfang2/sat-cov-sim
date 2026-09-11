"""Stable import path for the legacy single-frame compatibility API."""

from .compatibility.legacy_scenario import CoverageResult, CoverageScenario

__all__ = ["CoverageScenario", "CoverageResult"]
