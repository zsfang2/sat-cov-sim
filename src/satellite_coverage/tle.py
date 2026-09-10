"""TLE catalog handling and topocentric satellite selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class SatelliteState:
    norad_id: str
    name: str
    elevation_deg: float
    azimuth_deg: float
    slant_range_m: float
    altitude_m: float


class TleCatalog:
    def __init__(self, path: str | Path):
        from skyfield.api import EarthSatellite

        lines = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
        self._satellites: list[tuple[str, object]] = []
        index = 0
        while index < len(lines):
            name = ""
            if not lines[index].startswith("1 "):
                name = lines[index]
                index += 1
            if index + 1 < len(lines) and lines[index].startswith("1 ") and lines[index + 1].startswith("2 "):
                satellite = EarthSatellite(lines[index], lines[index + 1], name=name)
                self._satellites.append((name or satellite.model.satnum.__str__(), satellite))
                index += 2
            else:
                index += 1
        if not self._satellites:
            raise ValueError(f"No valid TLE pairs in {path}")

    def best_visible(self, when: datetime, lat: float, lon: float, min_elevation_deg: float = 5.0) -> SatelliteState:
        from skyfield.api import load, wgs84

        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        when = when.astimezone(timezone.utc)
        timescale = load.timescale()
        t = timescale.from_datetime(when)
        observer = wgs84.latlon(lat, lon)
        candidates: list[SatelliteState] = []
        for name, satellite in self._satellites:
            altitude, azimuth, distance = (satellite - observer).at(t).altaz()
            elevation_deg = float(altitude.degrees)
            if elevation_deg < min_elevation_deg:
                continue
            subpoint = wgs84.subpoint_of(satellite.at(t))
            candidates.append(SatelliteState(
                norad_id=str(satellite.model.satnum), name=name,
                elevation_deg=elevation_deg, azimuth_deg=float(azimuth.degrees),
                slant_range_m=float(distance.m), altitude_m=float(subpoint.elevation.m),
            ))
        if not candidates:
            raise LookupError("No satellite meets the visibility threshold")
        return sorted(candidates, key=lambda item: (-item.elevation_deg, int(item.norad_id)))[0]

