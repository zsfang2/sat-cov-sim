"""Public API for satellite-to-ground coverage simulation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .scenario import CoverageResult, CoverageScenario

__all__ = ["CoverageScenario", "CoverageResult"]


def __getattr__(name: str) -> Any:
    """Load the legacy public API only when a caller requests it."""
    if name in __all__:
        from .scenario import CoverageResult, CoverageScenario

        exports = {
            "CoverageScenario": CoverageScenario,
            "CoverageResult": CoverageResult,
        }
        globals().update(exports)
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
