"""Explicit units and coordinate-system identifiers for domain state."""

from __future__ import annotations

from enum import Enum


WGS84_GEODETIC_CRS = "EPSG:4326"
WGS84_ECEF_CRS = "EPSG:4978"


class DomainStateError(ValueError):
    """Raised when domain state is ambiguous, mutable, or inconsistent."""


class ArrayUnit(str, Enum):
    """Machine-readable unit assigned to every domain array."""

    DEGREE = "degree"
    METER = "meter"
    DB = "dB"
    DBM = "dBm"
    DIMENSIONLESS = "dimensionless"
    BOOLEAN = "boolean"
