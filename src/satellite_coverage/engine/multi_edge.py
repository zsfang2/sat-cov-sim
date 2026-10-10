"""Independent fixed-axis, positive-branch recursive diffraction reference.

Partition construction: NTIA TR-26-580, section 3.3.3. Single-edge
approximation: ITU-R P.526-16, equation 31. This explicitly named variant
is a numerical comparison model, not a measurement or a full ITU solver.
"""

import math


class ResourceLimit(ValueError):
    """The complete calculation cannot fit the declared solver budget."""


def solve_edges(points, *, length_m, frequency_hz, loss_cap_db=60.0,
                maximum_points=8192, maximum_depth=256, maximum_nodes=16383):
    """Solve (direct-ray projection, signed normal height) pairs in metres.

    Endpoints are (0, 0) and (length_m, 0). Duplicate projections use their
    highest silhouette. Budget refusal raises instead of returning a partial
    loss. Subpath distances use the original projection axis throughout.
    """
    for name, value in (("length_m", length_m), ("frequency_hz", frequency_hz),
                        ("loss_cap_db", loss_cap_db)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if length_m <= 0 or frequency_hz <= 0 or loss_cap_db < 0:
        raise ValueError("positive length/frequency and nonnegative cap required")
    for limit in (maximum_points, maximum_depth, maximum_nodes):
        if type(limit) is not int or limit < 1:
            raise ValueError("solver budgets must be positive integers")
    merged = {}
    count = 0
    for s, h in points:
        count += 1
        if count > maximum_points:
            raise ResourceLimit("maximum_points exceeded")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (s, h)):
            raise ValueError("edge coordinates must be finite")
        if not 0 < s < length_m:
            raise ValueError("edge projection outside open link interval")
        merged[s] = max(h, merged.get(s, -math.inf))
    edges = [(0.0, 0.0), *sorted(merged.items()), (float(length_m), 0.0)]
    wavelength = 299792458.0 / frequency_hz
    if not math.isfinite(wavelength) or wavelength <= 0:
        raise ValueError("wavelength outside numerical domain")
    stack = [(0, len(edges)-1, 1)]
    selected, terminations = [], []
    nodes = depth = 0
    while stack:
        a, b, level = stack.pop()
        nodes += 1
        depth = max(depth, level)
        if nodes > maximum_nodes or level > maximum_depth:
            raise ResourceLimit("maximum_nodes or maximum_depth exceeded")
        if b-a == 1:
            terminations.append("empty_partition")
            continue
        left, right = edges[a], edges[b]
        span = right[0]-left[0]
        best, index = -math.inf, None
        for i in range(a+1, b):
            s, h = edges[i]
            d1, d2 = s-left[0], right[0]-s
            relative = h-(left[1]+(right[1]-left[1])*(d1/span))
            scale = wavelength*(d1/span)*d2
            if not math.isfinite(scale) or scale <= 0:
                raise ValueError("subpath Fresnel radius outside numerical domain")
            v = math.sqrt(2)*relative/math.sqrt(scale)
            if not math.isfinite(v):
                raise ValueError("subpath Fresnel parameter outside numerical domain")
            if v > best:
                best, index = v, i
        if best <= -0.78:
            terminations.append("below_diffraction_cutoff")
            continue
        # Stable logarithmic form; implemented independently of the local solver.
        z = best-0.1
        log_term = math.log(math.hypot(z, 1.0)+z) if z <= 1e150 else math.log(z)+math.log(2)
        contribution = max(0.0, 6.9+20/math.log(10)*log_term)
        selected.append(dict(projection_m=edges[index][0], height_m=edges[index][1],
                             fresnel_v=best, loss_db=contribution, depth=level,
                             left_projection_m=left[0], right_projection_m=right[0]))
        if best <= 0:
            terminations.append("nonpositive_dominant_branch")
        else:
            stack.extend(((index, b, level+1), (a, index, level+1)))
    raw = math.fsum(edge["loss_db"] for edge in selected)
    return dict(raw_loss_db=raw, used_loss_db=min(raw, loss_cap_db),
                loss_cap_db=loss_cap_db, cap_triggered=raw > loss_cap_db,
                selected_edges=selected, termination_reasons=terminations,
                point_count=len(merged), duplicate_projection_count=count-len(merged),
                node_count=nodes, depth=depth,
                visibility="blocked" if any(h > 1e-8 for h in merged.values()) else "clear_within_radius",
                variant="recursive_dominant_edge_positive_branch_v1")
