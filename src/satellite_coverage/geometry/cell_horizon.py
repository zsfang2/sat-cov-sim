"""Horizon supremum of a piecewise-constant raster along one ray.

This visits every intersected cell interval instead of treating a finer uniform
step as truth. It is exact for that raster surface and the declared quadratic
curvature model, not for the real terrain represented by the raster.
"""

import math

from .terrain import terrain_profile


def cell_horizon(grid, *, receiver_east_m, receiver_north_m, antenna_agl_m,
                 azimuth_deg, radius_m, effective_radius_m=None):
    validated = terrain_profile(grid, receiver_east_m=receiver_east_m,receiver_north_m=receiver_north_m,
                                antenna_agl_m=antenna_agl_m,azimuth_deg=azimuth_deg,radius_m=radius_m,
                                step_m=min(grid.resolution_m,radius_m),effective_radius_m=effective_radius_m)
    ground = validated["receiver_ground_m"]
    if ground is None:
        return {"horizon_deg":None,"limiting_distance_m":None,"coverage_complete":False,
                "incomplete_reasons":["receiver_height_missing"],"cells_visited":0}
    direction = (math.sin(math.radians(azimuth_deg)),math.cos(math.radians(azimuth_deg)))
    cuts = {0.0,float(radius_m)}
    for origin, speed, boundary, spacing in (
        (receiver_east_m,direction[0],grid.west_m,grid.resolution_m),
        (receiver_north_m,direction[1],grid.north_m,grid.resolution_m)):
        if abs(speed) < 1e-14:
            continue
        finish = origin+radius_m*speed
        first = math.floor((min(origin,finish)-boundary)/spacing)
        last = math.ceil((max(origin,finish)-boundary)/spacing)
        for index in range(first,last+1):
            d = (boundary+index*spacing-origin)/speed
            if 0 < d < radius_m:
                cuts.add(d)
    cuts = sorted(cuts)
    best, limiting, reasons, visited = -math.inf, None, set(), 0
    for left,right in zip(cuts,cuts[1:]):
        if right-left < 1e-9:
            continue  # identical corner crossings within numerical precision
        middle = (left+right)/2
        height,status = grid.sample(receiver_east_m+middle*direction[0],receiver_north_m+middle*direction[1])
        visited += 1
        if height is None:
            reasons.add(status)
            continue
        delta = height-ground-antenna_agl_m
        candidates = [left,right]
        # slope(d) = delta/d - d/(2R). Its only possible interior maximum
        # occurs for negative delta, at sqrt(-2R*delta).
        if effective_radius_m is not None and delta < 0:
            critical = math.sqrt(-2*effective_radius_m*delta)
            if left < critical < right:
                candidates.append(critical)
        for d in candidates:
            if d == 0:
                angle = 0.0 if delta == 0 else (-90.0 if delta < 0 else 90.0)
            else:
                drop = 0 if effective_radius_m is None else d*d/(2*effective_radius_m)
                angle = math.degrees(math.atan2(delta-drop,d))
            if angle > best:
                best,limiting = angle,d
    return {"horizon_deg":best if limiting is not None else None,"limiting_distance_m":limiting,
            "coverage_complete":not reasons and limiting is not None,"incomplete_reasons":sorted(reasons),
            "cells_visited":visited,"radius_m":radius_m,
            "method":"cell-interval supremum with analytic curvature extrema",
            "scope":"piecewise-constant raster only; one-sided boundary limits; not a diffraction or real-terrain oracle"}
