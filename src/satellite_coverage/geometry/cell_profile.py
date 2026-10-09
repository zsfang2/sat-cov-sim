"""Profiles that retain both one-sided heights at every crossed cell boundary."""

import math

from .terrain import terrain_profile


def cell_profile(grid, *, receiver_east_m, receiver_north_m, antenna_agl_m,
                 azimuth_deg, radius_m, step_m, effective_radius_m=None):
    # Keep the public parameter validation and metadata contract. The uniform
    # samples are replaced below; the separate cell_horizon oracle is not used.
    result = terrain_profile(grid, receiver_east_m=receiver_east_m,
                             receiver_north_m=receiver_north_m, antenna_agl_m=antenna_agl_m,
                             azimuth_deg=azimuth_deg, radius_m=radius_m, step_m=step_m,
                             effective_radius_m=effective_radius_m)
    east = math.sin(math.radians(azimuth_deg))
    north = math.cos(math.radians(azimuth_deg))
    cuts = [0.0, float(radius_m)]
    for origin, velocity, edge, spacing, size in (
        (receiver_east_m, east, grid.west_m, grid.resolution_m, grid.elevations_m.shape[1]),
        (receiver_north_m, north, grid.north_m, -grid.resolution_m, grid.elevations_m.shape[0]),
    ):
        if abs(velocity) < 1e-14:
            continue
        finish = origin + velocity * radius_m
        indices = sorted(((origin-edge)/spacing, (finish-edge)/spacing))
        start = max(0, math.ceil(indices[0]))
        stop = min(size, math.floor(indices[1]))
        if stop-start > 100000:
            raise ValueError("cell profile exceeds 100000 boundary crossings")
        cuts.extend(d for index in range(start, stop+1)
                    if 0 < (d := (edge+index*spacing-origin)/velocity) < radius_m)
    cuts = sorted(set(cuts))
    if len(cuts) > 100002:
        raise ValueError("cell profile exceeds 100000 boundary crossings")
    ground = result["receiver_ground_m"]
    samples, intervals = [], []
    reasons = set()
    if ground is None:
        reasons.update(r for r in result["incomplete_reasons"] if r.startswith("receiver_"))
    for left, right in zip(cuts, cuts[1:]):
        if right-left < 1e-9:
            continue
        midpoint = (left+right)/2
        height, status = grid.sample(receiver_east_m+east*midpoint, receiver_north_m+north*midpoint)
        if status != "known":
            reasons.add(status)
        intervals.append({"start_m": left, "end_m": right, "elevation_m": height, "status": status})
        count = max(1, math.ceil((right-left)/step_m))
        distances = {left, right}
        distances.update(left+(right-left)*i/count for i in range(1, count))
        delta = None if height is None or ground is None else height-ground-antenna_agl_m
        if effective_radius_m is not None and delta is not None and delta < 0:
            critical = math.sqrt(-2*effective_radius_m*delta)
            if left < critical < right:
                distances.add(critical)
        for d in sorted(distances):
            drop = 0.0 if effective_radius_m is None else d*d/(2*effective_radius_m)
            relative = None if delta is None else delta-drop
            samples.append({"distance_m": d, "elevation_m": height, "status": status,
                            "curvature_drop_m": drop, "relative_height_m": relative,
                            "angle_deg": None if relative is None else math.degrees(math.atan2(relative, d)),
                            "interval_index": len(intervals)-1,
                            "boundary_side": "right_limit" if d == left else "left_limit" if d == right else "interior"})
        if len(samples) > 400000:
            raise ValueError("cell profile exceeds 400000 evaluation points")
    known = [s for s in samples if s["angle_deg"] is not None]
    limiting = max(known, key=lambda s: s["angle_deg"]) if known else None
    result.update(schema_version=2, sampling_method="cell_intervals",
                  sampling="piecewise-constant cell intervals; one-sided boundary limits and horizon extrema",
                  sampling_convergence="horizon extrema resolved for this raster; loss convergence not certified",
                  coverage_complete=not reasons, incomplete_reasons=sorted(reasons),
                  horizon_deg=limiting["angle_deg"] if limiting else None,
                  limiting_distance_m=limiting["distance_m"] if limiting else None,
                  horizon_status="known_within_radius" if not reasons else "lower_bound_or_unknown",
                  samples=samples, intervals=intervals)
    return result
