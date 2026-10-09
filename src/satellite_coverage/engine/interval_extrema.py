"""Stationary candidates for the declared local single-edge raster model.

With projected distance d, signed height h and link length L, v is proportional
to h/sqrt(d*(L-d)). Its stationary numerator is
2*h'*d*(L-d) - h*d'*(L-2*d). Work in normalized cell coordinates.
This is numerical polynomial root finding, not an independent physical model.
"""

import math

import numpy as np
from numpy.polynomial import Polynomial


def loss_extrema(profile, elevation_deg, slant_range_m, frequency_hz):
    angle = math.radians(elevation_deg)
    cosine, sine = math.cos(angle), math.sin(angle)
    curvature = profile["effective_radius_m"]
    ground = profile["receiver_ground_m"]
    if ground is None:
        return []
    antenna = ground + profile["antenna_agl_m"]
    wavelength = 299792458.0/frequency_hz
    output = []
    for index, interval in enumerate(profile["intervals"]):
        if interval["elevation_m"] is None:
            continue
        left, right = interval["start_m"], interval["end_m"]
        delta = interval["elevation_m"]-antenna
        coefficient = 0.0 if curvature is None else 1/(2*curvature)
        def projected(x):
            return x*cosine+(delta-coefficient*x*x)*sine
        # h decreases on x>=0 for the supported elevation/curvature range.
        # Bound the largest possible Fresnel radius to skip wholly zero-loss
        # intervals without changing the model's v<=-0.78 convention.
        distances = [projected(left), projected(right)]
        if coefficient*sine > 0:
            vertex = cosine/(2*coefficient*sine)
            if left < vertex < right:
                distances.append(projected(vertex))
                output.append({"distance_m": vertex,
                               "relative_height_m": delta-coefficient*vertex*vertex,
                               "interval_index": index, "candidate_kind": "projection_vertex"})
        if not all(math.isfinite(d) for d in distances):
            raise ValueError("terrain projection outside finite numerical range")
        lower, upper = max(0, min(distances)), min(slant_range_m, max(distances))
        if lower >= upper:
            continue
        peak = min(upper, max(lower, slant_range_m/2))
        fresnel_max = math.sqrt(wavelength*peak*(slant_range_m-peak)/slant_range_m)
        if not math.isfinite(fresnel_max) or fresnel_max <= 0:
            raise ValueError("terrain Fresnel radius outside finite numerical range")
        h_left = (delta-coefficient*left*left)*cosine-left*sine
        if h_left < 0 and math.sqrt(2)*h_left/fresnel_max <= -.78:
            continue
        # For positive h, increasing d<=L/2 makes v decrease. After h
        # becomes negative it cannot beat the positive left endpoint.
        if (h_left >= 0 and min(distances) > 0 and max(distances) <= slant_range_m/2
                and cosine-2*coefficient*right*sine >= 0):
            continue
        x = Polynomial([left, right-left])
        relative = Polynomial([delta])-coefficient*x*x
        d = x*cosine + relative*sine
        h = relative*cosine - x*sine
        numerator = 2*h.deriv()*d*(slant_range_m-d) - h*d.deriv()*(slant_range_m-2*d)
        scale = float(np.max(np.abs(numerator.coef)))
        if not math.isfinite(scale):
            raise ValueError("terrain stationary polynomial outside finite numerical range")
        if scale == 0:
            continue
        for root in (numerator/scale).roots():
            if abs(root.imag) > 1e-8 or not 0 < root.real < 1:
                continue
            t = float(root.real)
            distance = float(x(t))
            if not 0 < d(t) < slant_range_m:
                continue
            output.append({"distance_m": distance, "relative_height_m": float(relative(t)),
                           "interval_index": index, "candidate_kind": "stationary_fresnel_v"})
    return output
