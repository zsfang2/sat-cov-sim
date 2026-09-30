"""TLE inspection and clipped geometric visibility windows for a local explorer.

No weather, terrain masking, beam scheduling or communications service is implied.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import math

import numpy as np
from sgp4.io import verify_checksum
from skyfield.api import EarthSatellite, load, wgs84


TS = load.timescale(builtin=True)


def utc(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError("时间必须是带时区的 ISO 日期，例如 2025-01-01T00:00:00Z") from exc
    if result.tzinfo is None:
        raise ValueError("时间必须明确时区；界面时间采用 UTC")
    return result.astimezone(timezone.utc)


def iso(value):
    return datetime.fromtimestamp(float(value), timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def finite(value, name, low, high):
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是数值")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数值") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} 必须在 {low} 到 {high} 之间")
    return number


@dataclass
class Catalog:
    records: dict
    checksum: str
    record_count: int
    duplicate_count: int

    def summary(self):
        epochs = [r.epoch.utc_datetime().timestamp() for group in self.records.values() for r in group]
        return {"sha256": self.checksum, "records": self.record_count,
                "satellites": len(self.records), "duplicate_records": self.duplicate_count,
                "epoch_start": iso(min(epochs)), "epoch_end": iso(max(epochs)),
                "items": [{"norad_id": key, "name": group[0].name,
                           "records": len(group)} for key, group in sorted(self.records.items())]}


def parse_catalog(raw):
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("TLE 文件不得超过 32 MiB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("TLE 文件必须是 UTF-8 / ASCII 文本") from exc
    lines = [(i + 1, line.rstrip()) for i, line in enumerate(text.splitlines()) if line.strip()]
    groups, seen = {}, set()
    index, total, duplicates = 0, 0, 0
    while index < len(lines):
        number, first = lines[index]
        name = ""
        if not first.startswith("1 "):
            if first.startswith("2 "):
                raise ValueError(f"TLE 第 {number} 行缺少对应的第 1 行")
            name = first.removeprefix("0 ").strip()
            index += 1
        if index + 1 >= len(lines):
            raise ValueError(f"TLE 第 {number} 行之后缺少完整的两行轨道元素")
        number, first = lines[index]
        second = lines[index + 1][1]
        if not first.startswith("1 ") or not second.startswith("2 "):
            raise ValueError(f"TLE 第 {number} 行不是有效的两行元素对")
        if len(first) != 69 or len(second) != 69 or first[2:7] != second[2:7] or not first[68].isdigit() or not second[68].isdigit():
            raise ValueError(f"TLE 第 {number} 行：需各 69 字符且卫星编号一致")
        try:
            verify_checksum(first, second)
            satellite = EarthSatellite(first, second, name=name, ts=TS)
            model = satellite.model
            if not all(math.isfinite(v) for v in (model.ecco, model.inclo, model.no_kozai)):
                raise ValueError("nonfinite elements")
            if not 0 <= model.ecco < 1 or not 0 <= model.inclo <= math.pi or model.no_kozai <= 0:
                raise ValueError("invalid orbital elements")
            satellite.epoch.utc_datetime()
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"TLE 第 {number} 行解析或校验和失败：{exc}") from exc
        satellite.name = name or f"NORAD {model.satnum}"
        total += 1
        key = (first, second)
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
            # Line hash resolves ties at the same epoch independently of file order.
            satellite.record_sha256 = hashlib.sha256((first + "\n" + second).encode()).hexdigest()
            groups.setdefault(str(model.satnum), []).append(satellite)
        index += 2
    if not groups:
        raise ValueError("TLE 文件没有可用卫星")
    for group in groups.values():
        group.sort(key=lambda sat: (sat.epoch.utc_datetime(), sat.record_sha256))
    return Catalog(groups, hashlib.sha256(raw).hexdigest(), total, duplicates)


def select_record(group, start, policy="historical_exploration"):
    if policy not in ("historical_exploration", "past_only"):
        raise ValueError("TLE policy must be historical_exploration or past_only")
    past = [sat for sat in group if sat.epoch.utc_datetime() <= start]
    return past[-1] if past else (group[0] if policy == "historical_exploration" else None)


def observers(spec):
    height = finite(spec.get("height_m", 0), "WGS-84 椭球高", -500, 10000)
    mode = spec.get("mode", "point")
    if mode == "point":
        coordinates = [(finite(spec.get("lon"), "经度", -180, 180), finite(spec.get("lat"), "纬度", -89.9, 89.9))]
    elif mode == "region":
        west, south, east, north = bounds(spec.get("bounds"))
        n = spec.get("grid", 3)
        if type(n) is not int or n not in (2, 3, 5):
            raise ValueError("区域网格边长必须为 2、3 或 5")
        coordinates = [(float(x), float(y)) for y in np.linspace(south, north, n) for x in np.linspace(west, east, n)]
    else:
        raise ValueError("终端模式必须是 point 或 region")
    return [{"id": f"P{i + 1}", "lon": lon, "lat": lat, "height_m": height} for i, (lon, lat) in enumerate(coordinates)]


def bounds(values):
    if not isinstance(values, list) or len(values) != 4:
        raise ValueError("区域需提供 [西经度, 南纬度, 东经度, 北纬度]")
    west, south, east, north = [finite(v, "区域边界", -180 if i % 2 == 0 else -89.9,
                                     180 if i % 2 == 0 else 89.9) for i, v in enumerate(values)]
    if west >= east or south >= north:
        raise ValueError("区域必须西 < 东、南 < 北；暂不支持跨日期变更线区域")
    return west, south, east, north


def merge_intervals(groups, all_required=False):
    """Union/intersection of interval sets; positive-duration, half-open output."""
    if not groups:
        return []
    events = {}
    for group in groups:
        for start, end in group:
            if end > start:
                events[start] = events.get(start, 0) + 1
                events[end] = events.get(end, 0) - 1
    threshold = len(groups) if all_required else 1
    active, opening, result = 0, None, []
    for instant, delta in sorted(events.items()):
        before = active >= threshold
        active += delta
        after = active >= threshold
        if after and not before:
            opening = instant
        elif before and not after:
            result.append((opening, instant))
    return result


def altitude(sat, point, timestamps):
    times = TS.from_datetimes([datetime.fromtimestamp(float(t), timezone.utc) for t in timestamps])
    position = (sat - wgs84.latlon(point["lat"], point["lon"], elevation_m=point["height_m"])).at(times)
    messages = position.message
    if messages is not None and any(m for m in np.asarray(messages, dtype=object).ravel()):
        raise ValueError("SGP4 传播返回错误：" + str(messages))
    alt, az, distance = position.altaz()
    if not np.isfinite(alt.degrees).all():
        raise ValueError("SGP4 传播得到非有限坐标")
    return alt.degrees, az.degrees, distance.km


def point_windows(sat, point, start, end, minimum):
    begin, finish = start.timestamp(), end.timestamp()
    topo = wgs84.latlon(point["lat"], point["lon"], elevation_m=point["height_m"])
    # Check validity throughout the search, not just at visible events.
    altitude(sat, point, np.linspace(begin, finish, max(3, math.ceil((finish - begin) / 300) + 1)))
    times, events = sat.find_events(topo, TS.from_datetime(start), TS.from_datetime(end), altitude_degrees=minimum)
    stamps = np.array([dt.timestamp() for dt in times.utc_datetime()])
    if len(stamps):
        altitude(sat, point, stamps)
    opening = begin if altitude(sat, point, [begin])[0][0] >= minimum else None
    intervals = []
    for instant, event in zip(stamps, events):
        if event == 0 and opening is None:
            opening = max(begin, float(instant))
        elif event == 2 and opening is not None:
            intervals.append((opening, min(finish, float(instant))))
            opening = None
    if opening is not None:
        intervals.append((opening, finish))
    records = []
    for left, right in intervals:
        if right <= left:
            continue
        candidates = [left, right] + [float(t) for t, event in zip(stamps, events) if event == 1 and left <= t <= right]
        elevations = altitude(sat, point, candidates)[0]
        i = int(np.argmax(elevations))
        records.append({"start": left, "end": right, "peak_time": iso(candidates[i]),
                        "max_elevation_deg": float(elevations[i]),
                        "start_clipped": left == begin, "end_clipped": right == finish})
    return records


def request_parameters(data):
    if data.get("tle_policy", "historical_exploration") not in ("historical_exploration", "past_only"):
        raise ValueError("invalid tle_policy")
    start, end = utc(data.get("start")), utc(data.get("end"))
    if not 0 < (end - start).total_seconds() <= 7 * 86400:
        raise ValueError("结束时间必须晚于开始；单次演示最多计算 7 天")
    minimum = finite(data.get("min_elevation_deg", 10), "最低仰角", 0, 89)
    max_age = finite(data.get("max_age_days", 7), "TLE 最大历元偏差（天）", 0.01, 30)
    points = observers(data.get("observer", {}))
    rule = data.get("region_rule", "any")
    if rule not in ("any", "all"):
        raise ValueError("区域口径必须是 any 或 all")
    return start, end, minimum, max_age, points, rule


def calculate_visibility(catalog, data, progress=lambda *args: None, cancelled=lambda: False):
    start, end, minimum, max_age, points, rule = request_parameters(data)
    requested = data.get("satellite_ids")
    if requested is not None and (not isinstance(requested, list) or not requested or any(str(k) not in catalog.records for k in requested)):
        raise ValueError("指定卫星编号不存在或选择为空")
    ids = sorted(catalog.records) if requested is None else sorted(set(map(str, requested)))
    results, skipped, failed, windows = [], [], [], []
    point_unions = [[] for _ in points]
    for index, norad in enumerate(ids):
        if cancelled():
            raise InterruptedError("计算已取消")
        sat = select_record(catalog.records[norad], start, data.get("tle_policy", "historical_exploration"))
        if sat is None:
            skipped.append({"norad_id": norad, "reason": "no_tle_at_or_before_start"})
            progress(index + 1, len(ids), len(windows))
            continue
        epoch = sat.epoch.utc_datetime()
        age = max(abs((start - epoch).total_seconds()), abs((end - epoch).total_seconds())) / 86400
        identity = {"norad_id": norad, "name": sat.name, "epoch": epoch.isoformat().replace("+00:00", "Z"),
                    "record_sha256": sat.record_sha256, "max_epoch_offset_days": age,
                    "uses_future_epoch": epoch > start}
        if age > max_age:
            skipped.append({**identity, "reason": "TLE 历元偏差超过当前限制"})
        else:
            try:
                per_point = []
                for point in points:
                    if cancelled():
                        raise InterruptedError("计算已取消")
                    per_point.append(point_windows(sat, point, start, end, minimum))
                interval_groups = [[(w["start"], w["end"]) for w in group] for group in per_point]
                combined = merge_intervals(interval_groups, all_required=rule == "all")
                for p, group in enumerate(interval_groups):
                    point_unions[p].extend(group)
                for left, right in combined:
                    windows.append({**identity, "start": iso(left), "end": iso(right),
                                    "start_timestamp": left, "end_timestamp": right, "duration_s": right - left,
                                    "start_clipped": left == start.timestamp(), "end_clipped": right == end.timestamp()})
                results.append({**identity, "point_windows": [
                    {"point_id": point["id"], "windows": [{**w, "start": iso(w["start"]), "end": iso(w["end"])} for w in group]}
                    for point, group in zip(points, per_point)]})
            except (ValueError, RuntimeError) as exc:
                failed.append({**identity, "reason": str(exc)})
        progress(index + 1, len(ids), len(windows))
    # Across satellites, each point may use a different satellite for region-all.
    normalized = [merge_intervals([group]) for group in point_unions]
    coverage = merge_intervals(normalized, all_required=rule == "all")
    return {"request": data, "catalog_sha256": catalog.checksum, "points": points,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "software": {name: version(name) for name in ("skyfield", "sgp4", "numpy", "satellite-coverage-sim")},
            "selection_policy": data.get("tle_policy", "historical_exploration") + "; fixed_over_interval; sha256_tie_break",
            "scope": "geometric_elevation_only; no terrain/refraction/beam/service; region is sampled, not continuous",
            "event_search_tolerance_s": 0.5, "region_rule": rule,
            "windows": sorted(windows, key=lambda w: (w["start"], w["norad_id"])),
            "coverage_windows": [{"start": iso(a), "end": iso(b), "duration_s": b - a} for a, b in coverage],
            "covered_seconds": sum(b - a for a, b in coverage),
            "coverage_meaning": "any satellite per sample point; region-all may use different satellites at different points",
            "satellites_requested": len(ids), "satellites_computed": len(results),
            "satellites": results, "skipped": skipped, "failed": failed,
            "complete": not skipped and not failed}


def satellite_track(catalog, request, norad, point_index=0):
    start, end, _, max_age, points, _ = request_parameters(request)
    if norad not in catalog.records or type(point_index) is not int or not 0 <= point_index < len(points):
        raise ValueError("无效卫星或采样点")
    sat = select_record(catalog.records[norad], start, request.get("tle_policy", "historical_exploration"))
    if sat is None:
        raise ValueError("no_tle_at_or_before_start")
    if max(abs((t - sat.epoch.utc_datetime()).total_seconds()) for t in (start, end)) > max_age * 86400:
        raise ValueError("TLE epoch exceeds max_age_days")
    stamps = np.linspace(start.timestamp(), end.timestamp(), 721)
    alt, az, distance = altitude(sat, points[point_index], stamps)
    times = TS.from_datetimes([datetime.fromtimestamp(float(t), timezone.utc) for t in stamps])
    geo = wgs84.subpoint_of(sat.at(times))
    return {"point": points[point_index], "norad_id": norad, "scope": "721 samples for display only; windows use event search",
            "samples": [{"time": iso(t), "timestamp": float(t), "elevation_deg": float(a), "azimuth_deg": float(z),
                         "range_km": float(d), "lon": float(lon), "lat": float(lat)}
                        for t, a, z, d, lon, lat in zip(stamps, alt, az, distance, geo.longitude.degrees, geo.latitude.degrees)]}
