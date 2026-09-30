"""Paired local terrain sensitivity diagnostics, not global sufficiency proof."""

import numpy as np


def compare_profiles(candidate, reference, *, horizon_tolerance_deg=.1, loss_tolerance_db=1.0):
    """Compare matched (height, azimuth) rows; missingness prevents stability."""
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
