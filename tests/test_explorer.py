from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from satellite_coverage.data_sources.dem_preview import dem_info, dem_preview
from satellite_coverage.explorer.server import Explorer, handler_class
from test_visibility import TLE, request


def raster(path):
    array = np.arange(4096, dtype=np.int16).reshape(64, 64)
    array[:8, :8] = -9999
    with rasterio.open(path, "w", driver="GTiff", width=64, height=64, count=1,
                       dtype="int16", nodata=-9999, crs="EPSG:4326",
                       transform=from_bounds(108, 34, 109, 35, 64, 64)) as dst:
        dst.write(array, 1)
    return array


def test_dem_preserves_pixel_values_nodata_and_outside_extent(tmp_path):
    path = tmp_path / "dem.tif"
    array = raster(path)
    info = dem_info(path)
    assert info["bounds_wgs84"] == [108, 34, 109, 35]
    result = dem_preview(path, [108, 34, 109, 35], 64)
    actual = np.array(result["values"], dtype=float).reshape(64, 64)
    assert np.isnan(actual[:8, :8]).all()
    np.testing.assert_array_equal(actual[8:], array[8:])
    assert result["valid_fraction"] == pytest.approx(1 - 64/4096)
    assert info["unit"] == "unknown" and not info["physical_use_ready"]
    partial = dem_preview(path, [107.5, 34, 108.5, 35], 64)
    assert np.isnan(np.array(partial["values"], dtype=float).reshape(64, 64)[:, :32]).all()
    with pytest.raises(ValueError, match="不与 DEM 相交"):
        dem_preview(path, [0, 1, 2, 3])


def test_http_catalog_job_track_dem_and_path_scope(tmp_path):
    (tmp_path / "test.tle").write_bytes(TLE)
    raster(tmp_path / "dem.tif")
    app = Explorer(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    def call(path, data=None):
        req = Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                      headers={"Content-Type": "application/json", "X-Explorer": "1"})
        with urlopen(req, timeout=15) as response:
            return json.load(response)
    try:
        assert call("/api/health")["api_version"] == 1
        assert call("/")["service"] == "satellite-coverage-sim"
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/app.js")
        assert error.value.code == 404
        catalog = call("/api/catalog", {"path": "test.tle"})
        uploaded = call("/api/catalog", {"text": TLE.decode(), "name": "upload.tle"})
        assert catalog["catalog_id"] == uploaded["catalog_id"]
        data = {**request(), "catalog_id": catalog["catalog_id"]}
        job_id = call("/api/visibility", data)["job_id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = call("/api/job?id=" + job_id)
            if job["state"] not in ("running", "queued"):
                break
            time.sleep(.02)
        assert job["state"] == "done" and job["result"]["windows"]
        track = call("/api/track", {"job_id": job_id, "norad_id": "44714"})
        assert len(track["samples"]) == 721
        preview = call("/api/dem", {"path": "dem.tif", "bounds": [108, 34, 109, 35], "size": 64})
        assert preview["values"][0] is None
        with pytest.raises(HTTPError) as error:
            call("/api/dem-info", {"path": "/etc/passwd"})
        assert error.value.code == 400
        with pytest.raises(HTTPError):
            urlopen(Request(base + "/api/catalog", data=b'{}', headers={"Origin": "https://example.com"}))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        app.pool.shutdown(wait=True)
