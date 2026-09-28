"""Native-resolution DEM window inspection; no filling or resampling."""

import math
import numpy as np


def audit_dem_window(path, longitude_deg, latitude_deg, window_size_px,
                     vertical_crs=None, vertical_unit=None):
    import rasterio
    from rasterio.windows import Window, bounds as window_bounds
    from pyproj import CRS, Transformer, Geod

    if vertical_crs is not None and not CRS.from_user_input(vertical_crs).is_vertical:
        raise ValueError("declared vertical_crs must identify a vertical CRS")
    if vertical_unit is not None and vertical_unit != "metre":
        raise ValueError("only explicitly declared metre elevations are supported")
    if type(window_size_px) is not int or window_size_px < 1:
        raise ValueError("window_size_px must be a positive integer")
    if (isinstance(longitude_deg, bool) or isinstance(latitude_deg, bool)
        or not math.isfinite(longitude_deg) or not math.isfinite(latitude_deg)
        or not -180 <= longitude_deg <= 180 or not -90 <= latitude_deg <= 90):
        raise ValueError("invalid WGS84 point")
    with rasterio.open(path) as source:
        if source.crs is None:
            raise ValueError("DEM has no horizontal CRS")
        if source.transform.b or source.transform.d or source.transform.a <= 0 or source.transform.e >= 0:
            raise ValueError("audit currently requires a north-up raster")
        transform = Transformer.from_crs("EPSG:4326", source.crs, always_xy=True)
        x, y = transform.transform(longitude_deg, latitude_deg)
        row, col = source.index(x, y)
        half = window_size_px // 2
        window = Window(col - half, row - half, window_size_px, window_size_px)
        if window.col_off < 0 or window.row_off < 0 or window.col_off + window.width > source.width or window.row_off + window.height > source.height:
            raise ValueError("DEM does not cover the full requested window")
        raw = source.read(1, window=window, masked=True)
        mask = np.ma.getmaskarray(raw) | ~np.isfinite(raw.data)
        values = raw.data[~mask]
        left, bottom, right, top = window_bounds(window, source.transform)
        to_geo = Transformer.from_crs(source.crs, "EPSG:4326", always_xy=True)
        geod = Geod(ellps="WGS84")
        def distance(px, py):
            lon, lat = to_geo.transform(px, py)
            return abs(float(geod.inv(longitude_deg, latitude_deg, lon, lat)[2]))
        edge_distances = {"west": distance(left, y), "east": distance(right, y),
                          "south": distance(x, bottom), "north": distance(x, top)}
        native_unit = CRS.from_user_input(source.crs).axis_info[0].unit_name
        report = {
            "horizontal_crs": source.crs.to_string(), "vertical_crs": vertical_crs,
            "vertical_crs_status": "declared" if vertical_crs else "unknown",
            "vertical_unit": vertical_unit, "vertical_unit_status": "declared" if vertical_unit else "unknown",
            "source_shape": [source.height, source.width], "source_transform": list(source.transform)[:6],
            "window": {"row_off": int(window.row_off), "col_off": int(window.col_off),
                       "height": window_size_px, "width": window_size_px},
            "window_transform": list(source.window_transform(window))[:6],
            "bounds_in_source_crs": [left, bottom, right, top],
            "first_pixel_center_in_source_crs": list(source.xy(window.row_off, window.col_off)),
            "pixel_size": [abs(source.transform.a), abs(source.transform.e)], "pixel_size_unit": native_unit,
            "nodata": float(source.nodata) if source.nodata is not None and math.isfinite(source.nodata) else None,
            "nodata_repr": str(source.nodata), "dtype": str(raw.dtype),
            "valid_fraction": float((~mask).mean()), "missing_pixels": int(mask.sum()),
            "valid_min": float(values.min()) if values.size else None,
            "valid_max": float(values.max()) if values.size else None,
            "valid_mean": float(values.mean()) if values.size else None,
            "source_tags": source.tags(), "resampling": "none", "filling": "none",
            "candidate_wgs84": [longitude_deg, latitude_deg],
            "window_edge_distance_m": edge_distances,
            "available_window_buffer_m": min(edge_distances.values()),
            "buffer_method": "WGS84 distances to window axis intersections; diagnostic only",
            "horizon_range_sufficiency": "undetermined",
            "elevation_metadata_and_window_complete": bool(vertical_crs and vertical_unit and values.size and not mask.any()),
            "physical_use_ready": False,
            "physical_use_note": "audit alone does not validate vertical alignment, propagation radius or terrain solver",
        }
        return report, raw.data.copy(), mask.copy()
