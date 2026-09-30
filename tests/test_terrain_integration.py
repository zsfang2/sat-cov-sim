from copy import deepcopy
from pathlib import Path

import numpy as np
from pyproj import CRS
import pytest
import rasterio
from rasterio.transform import from_origin
import yaml

from satellite_coverage.data_sources.manifest import checksum_sha256
from satellite_coverage.data_sources.terrain_dem import load_terrain_dem
from satellite_coverage.engine.links import calculate_links
from satellite_coverage.engine.terrain_context import TerrainContext
from satellite_coverage.geometry.terrain import TerrainGrid

ROOT = Path(__file__).resolve().parents[1]


def config():
    data = yaml.safe_load((ROOT / "configs/m1_fixed.yaml").read_text())
    data["receiver"]["antenna_ellipsoid_height_m"] = 2
    data["source"] = {"mode": "direction_sequence", "candidate_id": "test", "directions": [
        {"azimuth_deg": 0, "elevation_deg": 30, "slant_range_m": 550000}]*3}
    return data


def context(heights=None, **kwargs):
    grid = TerrainGrid(np.zeros((41,41)) if heights is None else heights, -205,205,10,
                       "WGS84_ellipsoid", "synthetic-test")
    return TerrainContext(grid, 0,0,150,10, **kwargs)


def raster(tmp_path, **kwargs):
    path = tmp_path / "height.tif"
    heights = np.zeros((41,41), dtype="float32")
    heights[10,:] = 102
    heights[0,0] = -9999
    options = dict(driver="GTiff", width=41, height=41, count=1, dtype="float32",
                   crs=CRS.from_proj4("+proj=aeqd +lat_0=0 +lon_0=0 +datum=WGS84 +units=m"),
                   transform=from_origin(-205,205,10,10), nodata=-9999)
    options.update(kwargs)
    with rasterio.open(path,"w",**options) as dst:
        dst.write(heights,1)
    return path, {"sha256": checksum_sha256(path), "height_unit":"m", "vertical_datum":"WGS84_ellipsoid", "surface_type":"synthetic",
                  "evidence":"Synthetic GeoTIFF with declared ellipsoid metre heights; test only"}


def load(path, declaration, **kwargs):
    options = dict(lon_deg=0,lat_deg=0,radius_m=150,resolution_m=10)
    options.update(kwargs)
    return load_terrain_dem(path,declaration,**options)


def test_geotiff_to_m1_ridge_once_and_identity(tmp_path):
    path, declaration = raster(tmp_path)
    grid, metadata = load(path,declaration)
    terrain = TerrainContext(grid,0,0,150,10)
    baseline = calculate_links(config())
    result = calculate_links(config(), terrain=terrain)
    record = result["records"][0]
    assert result["complete"] and record["terrain"]["los_status"] == "blocked"
    assert record["terrain"]["profile"]["horizon_deg"] == pytest.approx(45)
    power = record["budget"]["received_power"]["value"]
    loss = record["terrain"]["used_loss_db"]
    assert power == pytest.approx(baseline["records"][0]["budget"]["received_power"]["value"]-loss)
    components = record["budget"]["components"]
    local = [c for c in components if c["name"] == "local"]
    assert len(local) == 1 and local[0]["enabled"] and local[0]["solver"] == "local-dominant-knife-edge-v1"
    assert metadata["file_sha256"] == declaration["sha256"]
    assert result["physical_input_checksum"] != calculate_links(config(),terrain=context())["physical_input_checksum"]


@pytest.mark.parametrize("field,value", [("vertical_datum","EGM96"),("height_unit","ft"),("sha256","bad"),("evidence","")])
def test_unverified_height_declarations_rejected(tmp_path, field, value):
    path, declaration = raster(tmp_path)
    declaration[field] = value
    with pytest.raises(ValueError):
        load(path,declaration)


def test_resolution_and_memory_bounds(tmp_path):
    path, declaration = raster(tmp_path)
    with pytest.raises(ValueError, match="finer"):
        load(path,declaration,resolution_m=5)
    with pytest.raises(ValueError, match="million"):
        load(path,declaration,radius_m=100000)
    grid, _ = load(path,declaration,radius_m=300)
    assert np.isnan(grid.elevations_m).any()
    result = calculate_links(config(), terrain=TerrainContext(grid,0,0,300,10))
    assert not result["complete"]
    assert result["records"][0]["budget"]["received_power"]["status"] == "not_computed"


def test_scale_offset_and_nodata_preserved(tmp_path):
    path, declaration = raster(tmp_path)
    with rasterio.open(path,"r+") as dst:
        dst.scales = [2]
        dst.offsets = [5]
    declaration["sha256"] = checksum_sha256(path)
    grid, metadata = load(path,declaration,radius_m=210)
    assert grid.sample(0,0)[0] == 5
    assert grid.sample(0,100)[0] == 209
    assert np.isnan(grid.elevations_m).any()


def test_double_counting_and_receiver_mismatch_rejected():
    data = config()
    data["budget"]["losses"]["local"] = {"enabled":True,"status":"known","value":0,"reason":"other solver"}
    with pytest.raises(ValueError, match="duplicate"):
        calculate_links(data, terrain=context())
    data = config()
    data["receiver"]["lon_deg"] = 1
    with pytest.raises(ValueError, match="origin"):
        calculate_links(data,terrain=context())
    with pytest.raises(ValueError, match="below"):
        calculate_links(config(),terrain=context(np.full((41,41),10)))


@pytest.mark.parametrize("kind", ["nodata","receiver_nodata","zenith","below"])
def test_missing_and_special_geometry_not_forced_clear(kind):
    heights = np.zeros((41,41))
    data = config()
    if kind == "nodata": heights[10,20] = np.nan
    if kind == "receiver_nodata": heights[20,20] = np.nan
    if kind in ("zenith","below"):
        for d in data["source"]["directions"]:
            d["elevation_deg"] = 90 if kind == "zenith" else -10
    result = calculate_links(data,terrain=context(heights))
    record = result["records"][0]
    assert record["budget"]["received_power"]["status"] == ("not_applicable" if kind == "below" else "not_computed")
    if kind != "below": assert not result["complete"]


def test_far_ridge_radius_sensitivity_not_global_clear():
    heights = np.zeros((41,41))
    heights[3,:] = 200  # north 170 m: outside the first profile
    short = context(heights)
    longer = TerrainContext(short.grid,0,0,190,10)
    a, b = [calculate_links(config(),terrain=t)["records"][0]["terrain"] for t in (short,longer)]
    assert a["los_status"] == "clear_within_radius" and a["truncated_before_satellite"]
    assert b["los_status"] == "blocked"


def test_explicit_egm2008_conversion_sign_and_missing_grid(tmp_path):
    path, declaration = raster(tmp_path)
    declaration["vertical_datum"] = "EGM2008"
    declaration["surface_type"] = "DSM"
    with pytest.raises(ValueError, match="geoid"):
        load(path,declaration)
    geoid_path = tmp_path / "synthetic geoid.tif"
    with rasterio.open(geoid_path,"w",driver="GTiff",width=4,height=4,count=1,dtype="float32",
                       crs="EPSG:4326",transform=from_origin(-2,2,1,1)) as dst:
        dst.write(np.full((4,4),12,dtype="float32"),1)
        dst.update_tags(TYPE="VERTICAL_OFFSET_GEOGRAPHIC_TO_VERTICAL",target_crs_epsg_code="3855")
        dst.set_band_description(1,"geoid_undulation")
        dst.set_band_unit(1,"metre")
    geoid = {"path":str(geoid_path),"sha256":checksum_sha256(geoid_path),"model":"EGM2008",
             "evidence":"Synthetic +12 m test field; not real EGM2008 values"}
    grid, metadata = load(path,declaration,geoid=geoid)
    assert grid.sample(0,0)[0] == pytest.approx(12)
    assert grid.sample(0,100)[0] == pytest.approx(114)
    assert grid.surface_type == "DSM"
    assert metadata["vertical_conversion"]["grid"]["sha256"] == geoid["sha256"]
    declaration["vertical_datum"] = "WGS84_ellipsoid"
    with pytest.raises(ValueError, match="double-convert"):
        load(path,declaration,geoid=geoid)


def test_unified_cli_archives_terrain_input_and_result(tmp_path):
    import json
    from satellite_coverage.experiments.link import execute
    path, declaration = raster(tmp_path)
    cfg = tmp_path / "link.yaml"
    cfg.write_text(yaml.safe_dump(config()))
    terrain_cfg = tmp_path / "terrain.yaml"
    terrain_cfg.write_text(yaml.safe_dump({"dem_path":path.name,"declaration":declaration,"geoid":None,
                                         "radius_m":150,"resolution_m":10,"step_m":10,
                                         "effective_radius_m":None,"loss_cap_db":60}))
    result = execute(cfg,None,tmp_path/"run",ROOT,terrain_cfg)
    assert result["complete"]
    assert (tmp_path/"run/terrain_ellipsoid_m.npy").exists()
    assert "terrain.json" in json.loads((tmp_path/"run/artifacts.json").read_text())["files"]


def test_horizon_sampling_guard_withholds_unconverged_power():
    heights = np.zeros((41,41))
    heights[10,:] = 102
    terrain = context(heights,horizon_tolerance_deg=.1)
    result = calculate_links(config(),terrain=terrain)
    row = result["records"][0]
    assert not result["complete"]
    assert row["terrain"]["sampling_audit"]["horizon_error_deg"] > .1
    assert row["terrain"]["diagnostic_sampled_loss_db"] > 0
    assert row["budget"]["received_power"]["status"] == "not_computed"
    assert row["terrain"]["raw_loss_db"] is None
    flat = calculate_links(config(),terrain=context(horizon_tolerance_deg=.1))
    assert flat["complete"] and flat["records"][0]["terrain"]["sampling_audit"]["passed"]
