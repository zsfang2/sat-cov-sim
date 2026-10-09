import importlib.util
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine, from_origin

from satellite_coverage.data_sources.manifest import checksum_sha256
from satellite_coverage.data_sources.terrain_dem import load_terrain_dem
from satellite_coverage.data_sources.terrain_tiles import TerrainReadBudget, indices
from test_terrain_integration import raster, load


spec = importlib.util.spec_from_file_location('terrain_legacy', Path(__file__).parent/'fixtures/terrain_dem_legacy.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


@pytest.mark.parametrize('tile_size', [7, 128])
@pytest.mark.parametrize('transform', [from_origin(-205,205,10,10),
                                     Affine.translation(-205,205)*Affine.rotation(12)*Affine.scale(10,-10)])
def test_exact_legacy_values_mask_metadata_and_budget(tmp_path, tile_size, transform):
    path, declaration = raster(tmp_path, transform=transform)
    with rasterio.open(path, 'r+') as dst:
        data = np.random.default_rng(7).normal(size=(41,41)).astype('float32')
        data[18:22,18:22] = -9999
        dst.write(data, 1)
        dst.scales, dst.offsets = [2], [5]
    declaration['sha256'] = checksum_sha256(path)
    options = dict(lon_deg=0, lat_deg=0, radius_m=260, resolution_m=10)
    old, old_meta = oracle.load_terrain_dem(path, declaration, **options)
    stats, windows = {}, []
    new, meta = load_terrain_dem(path, declaration, **options,
                                read_budget=TerrainReadBudget(tile_size=tile_size, source_window_cells=64),
                                diagnostics=stats, window_observer=windows.append)
    assert np.array_equal(new.elevations_m, old.elevations_m, equal_nan=True)
    assert np.array_equal(np.isnan(new.elevations_m), np.isnan(old.elevations_m))
    assert new.source_id == old.source_id and meta == old_meta
    assert all(w*h <= 64 for _,_,w,h in windows)
    assert stats['read_cells'] == sum(w*h for _,_,w,h in windows)
    assert stats['read_windows'] == len(windows)
    if tile_size == 128:
        assert stats['subdivisions'] > 0


def test_geoid_exact_across_tiles(tmp_path):
    path, declaration = raster(tmp_path)
    declaration['vertical_datum'] = 'EGM2008'
    gp = tmp_path/'geoid.tif'
    with rasterio.open(gp, 'w', driver='GTiff', width=4, height=4, count=1,
                       dtype='float32', crs='EPSG:4326', transform=from_origin(-2,2,1,1)) as dst:
        dst.write(np.arange(16,dtype='float32').reshape(4,4),1)
        dst.update_tags(TYPE='VERTICAL_OFFSET_GEOGRAPHIC_TO_VERTICAL',target_crs_epsg_code='3855')
        dst.set_band_description(1,'geoid_undulation')
    geoid = dict(path=str(gp), sha256=checksum_sha256(gp), model='EGM2008', evidence='synthetic')
    opts = dict(lon_deg=0, lat_deg=0, radius_m=220, resolution_m=10, geoid=geoid)
    old, metadata = oracle.load_terrain_dem(path, declaration, **opts)
    for tile in (5,128):
        new, actual = load_terrain_dem(path, declaration, **opts, read_budget=TerrainReadBudget(tile_size=tile))
        assert np.array_equal(new.elevations_m, old.elevations_m, equal_nan=True)
        assert actual == metadata and new.source_id == old.source_id


@pytest.mark.parametrize('budget', [TerrainReadBudget(target_cells=1), TerrainReadBudget(memory_bytes=1)])
def test_budget_fails_before_coordinates_or_read(tmp_path, monkeypatch, budget):
    path, declaration = raster(tmp_path)
    monkeypatch.setattr(np, 'meshgrid', lambda *a, **k: pytest.fail('allocated coordinates before budget check'))
    with pytest.raises(ValueError, match='budget'):
        load(path, declaration, read_budget=budget)


@pytest.mark.parametrize('kwargs', [dict(tile_size=0), dict(tile_size=129),
                                  dict(source_window_cells=0), dict(target_cells=True),
                                  dict(memory_bytes=513*1024**2)])
def test_invalid_resource_options(kwargs):
    with pytest.raises(ValueError):
        TerrainReadBudget(**kwargs)


def test_empty_intersection_and_missing_crs(tmp_path):
    path, declaration = raster(tmp_path, transform=from_origin(10000,10000,10,10))
    with pytest.raises(ValueError, match='intersect'):
        load(path, declaration)
    path, declaration = raster(tmp_path, crs=None)
    with pytest.raises(ValueError, match='CRS'):
        load(path, declaration)


def test_source_indices_floor_and_nonfinite():
    class Source:
        transform = Affine.identity()
        width = height = 10
    class Transform:
        def transform(self, x, y, **kwargs):
            return np.array([[-1e-12, 0, .999999999999, 1, 10]]), np.zeros((1,5))
    cols, rows, valid = indices(Source(), Transform(), (0,1,0,5), 0, 1)
    assert cols[valid].tolist() == [0,0,1]
    assert valid.tolist() == [[False,True,True,True,False]]
    class Broken:
        def transform(self, x, y, **kwargs):
            return x*np.nan, y
    with pytest.raises(ValueError, match='nonfinite'):
        indices(Source(), Broken(), (0,1,0,5), 0, 1)


def test_single_pixel_reads_terminate_and_preserve_values(tmp_path):
    path, declaration = raster(tmp_path)
    old, _ = load(path, declaration)
    stats = {}
    new, _ = load(path, declaration, read_budget=TerrainReadBudget(source_window_cells=1), diagnostics=stats)
    assert stats['max_read_cells'] == 1
    assert np.array_equal(new.elevations_m, old.elevations_m, equal_nan=True)


def test_native_block_memory_reservation():
    budget = TerrainReadBudget(memory_bytes=300*1024**2)
    with pytest.raises(ValueError, match='memory'):
        budget.check_memory(100, block_cells=4_000_000, itemsize=8)


def test_large_source_extent_is_subdivided_without_decimation(tmp_path):
    path = tmp_path/'large.tif'
    data = (np.arange(2601)[:,None] + np.arange(2601)[None,:]).astype('int16')
    with rasterio.open(path,'w',driver='GTiff',width=2601,height=2601,count=1,
                       dtype='int16',crs='+proj=aeqd +lat_0=0 +lon_0=0 +datum=WGS84 +units=m',
                       transform=from_origin(-1300.5,1300.5,1,1),tiled=True,
                       blockxsize=256,blockysize=256) as dst:
        dst.write(data,1)
    declaration = dict(sha256=checksum_sha256(path),height_unit='m',vertical_datum='WGS84_ellipsoid',
                       surface_type='synthetic',evidence='controlled integer cell ramp')
    opts = dict(lon_deg=0,lat_deg=0,radius_m=1200,resolution_m=10)
    with pytest.raises(ValueError,match='four million'):
        oracle.load_terrain_dem(path,declaration,**opts)
    stats = {}
    grid, meta = load_terrain_dem(path,declaration,**opts,diagnostics=stats)
    assert meta['native_window'][2]*meta['native_window'][3] > 4_000_000
    assert grid.elevations_m.shape == (243,243) and grid.resolution_m == 10
    row = 1300 + (np.arange(243)-121)*10
    col = 1300 + (np.arange(243)-121)*10
    assert np.array_equal(grid.elevations_m, data[row[:,None],col[None,:]])
    assert stats['subdivisions'] > 0 and stats['max_read_cells'] <= 262_144
