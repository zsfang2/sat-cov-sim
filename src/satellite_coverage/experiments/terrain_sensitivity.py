"""Paired local terrain sensitivity diagnostics, not global sufficiency proof."""

import numpy as np

from ..geometry.geodetic import finite_number


def compare_profiles(candidate, reference, *, horizon_tolerance_deg=.1, loss_tolerance_db=1.0):
    """Compare matched (height, azimuth) rows; missingness prevents stability."""
    for name, value in (("horizon_tolerance_deg", horizon_tolerance_deg), ("loss_tolerance_db", loss_tolerance_db)):
        finite_number(value, name)
        if value < 0:
            raise ValueError("comparison tolerances must be nonnegative")
    def indexed(rows):
        result = {}
        for row in rows:
            key = (row["height_above_surface_m"], row["azimuth_deg"])
            if key in result:
                raise ValueError("duplicate comparison direction/height")
            result[key] = row
        return result
    a, b = indexed(candidate), indexed(reference)
    if set(a) != set(b) or not a:
        raise ValueError("comparison requires identical nonempty direction/height sets")
    horizon_errors, loss_errors = [], []
    flips, paired_queries, unavailable = 0, 0, 0
    for key in a:
        left, right = a[key], b[key]
        if not left["coverage_complete"] or not right["coverage_complete"]:
            unavailable += 1
            continue
        horizon_errors.append(abs(left["horizon_deg"]-right["horizon_deg"]))
        if set(left["queries"]) != set(right["queries"]):
            raise ValueError("comparison elevations differ")
        for elevation in left["queries"]:
            p, q = left["queries"][elevation], right["queries"][elevation]
            if p["loss_status"] != "known" or q["loss_status"] != "known":
                unavailable += 1
                continue
            paired_queries += 1
            loss_errors.append(abs(p["raw_loss_db"]-q["raw_loss_db"]))
            flips += p["los_status"] != q["los_status"]
    def stats(values):
        return {"max": max(values), "p95": float(np.percentile(values,95))} if values else {"max":None,"p95":None}
    stable = bool(horizon_errors and loss_errors) and not unavailable and not flips and max(horizon_errors)<=horizon_tolerance_deg and max(loss_errors)<=loss_tolerance_db
    return {"profile_pairs":len(a),"paired_queries":paired_queries,"unavailable_pairs_or_queries":unavailable,
            "horizon_error_deg":stats(horizon_errors),"raw_loss_error_db":stats(loss_errors),
            "los_classification_changes":int(flips),"stable_under_diagnostic_thresholds":bool(stable),
            "diagnostic_thresholds":{"horizon_deg":horizon_tolerance_deg,"raw_loss_db":loss_tolerance_db,"los_changes":0},
            "scope":"paired finite-radius sampled DSM comparison; reference is not ground truth"}


def assess_radius_stability(rows, *, horizon_tolerance_deg=.1, loss_tolerance_db=1.0,
                            minimum_extensions=2):
    """Compare each radius to EVERY larger tested radius on the same input grid.

    Callers must hold the DEM/grid, receiver and link parameters fixed. No
    finite sweep can prove absence of an obstacle outside its maximum radius.
    """
    if type(minimum_extensions) is not int or minimum_extensions < 1:
        raise ValueError("minimum_extensions must be a positive integer")
    grouped = {}
    for row in rows:
        radius = row["radius_m"]
        finite_number(radius, "radius_m")
        if not 0 < radius <= 100000:
            raise ValueError("radius must be in (0, 100000]")
        grouped.setdefault(radius, []).append(row)
    if len(grouped) < 2:
        raise ValueError("radius audit requires at least two radii")
    radii = sorted(grouped)
    entries = []
    for index, radius in enumerate(radii):
        comparisons = [{"reference_radius_m": other,
                        **compare_profiles(grouped[radius], grouped[other],
                                           horizon_tolerance_deg=horizon_tolerance_deg,
                                           loss_tolerance_db=loss_tolerance_db)}
                       for other in radii[index+1:]]
        # Validate even the maximum-radius rows via a self comparison. Missing
        # data must not be hidden behind a lack of larger-radius evidence.
        own = compare_profiles(grouped[radius], grouped[radius],
                               horizon_tolerance_deg=horizon_tolerance_deg,
                               loss_tolerance_db=loss_tolerance_db)
        if own["unavailable_pairs_or_queries"] or any(c["unavailable_pairs_or_queries"] for c in comparisons):
            status = "unknown_missing_or_unsupported_queries"
        elif any(not c["stable_under_diagnostic_thresholds"] for c in comparisons):
            status = "changed_with_expansion"
        elif len(comparisons) < minimum_extensions:
            status = "insufficient_larger_radius_evidence"
        else:
            status = "stable_within_tested_extent"
        entries.append({"radius_m": radius, "status": status, "comparisons": comparisons})
    stable = [e["radius_m"] for e in entries if e["status"] == "stable_within_tested_extent"]
    return {"radii_m": radii, "maximum_tested_radius_m": radii[-1],
            "minimum_extensions": minimum_extensions,
            "smallest_stable_tested_radius_m": min(stable) if stable else None,
            "global_radius_sufficiency": "not_verified",
            "scope": "fixed-input diagnostic comparisons; no guarantee beyond maximum tested radius or between directions",
            "entries": entries}
