"""Fresh-process reader resource/equivalence worker; outputs never overwritten."""

import argparse
import importlib.util
import json
from pathlib import Path
import platform
import resource
import time
import zipfile

import numpy as np
import rasterio
import pyproj

from satellite_coverage.data_sources.manifest import checksum_sha256
from satellite_coverage.data_sources.terrain_dem import load_terrain_dem
from satellite_coverage.data_sources.terrain_tiles import TerrainReadBudget


def window_union_cells(windows):
    """Exact rectangle union via row intervals, for this diagnostic only."""
    rows = {}
    for c, r, width, height in windows:
        for row in range(r, r+height):
            rows.setdefault(row, []).append((c,c+width))
    count = 0
    for intervals in rows.values():
        end = -1
        for left, right in sorted(intervals):
            count += max(0, right-max(left,end))
            end = max(end, right)
    return count


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dem', type=Path, required=True)
    p.add_argument('--geoid', type=Path, required=True)
    p.add_argument('--radius-m', type=float, required=True)
    p.add_argument('--mode', choices=('legacy','bounded'), default='bounded')
    p.add_argument('--tile-size', type=int, default=128)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    evidence = json.loads((root/'reports/m3/copernicus-source.json').read_text())
    ge = json.loads((root/'reports/m3/egm2008-grid.json').read_text())
    declaration = dict(sha256=evidence['local_sha256'],height_unit='m',vertical_datum='EGM2008',
                       surface_type='DSM',evidence=evidence['source_assessment'])
    geoid = dict(path=str(args.geoid.resolve()),sha256=ge['sha256'],model='EGM2008',evidence=ge['url'])
    record = dict(mode=args.mode,radius_m=args.radius_m,site=[108.9,34.24],resolution_m=60,
                  declaration=declaration,geoid=geoid,
                  versions=dict(python=platform.python_version(),numpy=np.__version__,
                                gdal=rasterio.__gdal_version__,proj=pyproj.proj_version_str),
                  stats={},source_hashes={})
    # Include actual working source, including newly added/uncommitted modules.
    with zipfile.ZipFile(args.output/'sources.zip','w',zipfile.ZIP_DEFLATED) as archive:
        paths = sorted((root/'src').rglob('*.py')) + [Path(__file__),root/'tests/fixtures/terrain_dem_legacy.py']
        for path in paths:
            name = str(path.relative_to(root))
            archive.write(path,name)
            record['source_hashes'][name] = checksum_sha256(path)
    reader = load_terrain_dem
    extra, windows = {}, []
    if args.mode == 'legacy':
        spec = importlib.util.spec_from_file_location('legacy',root/'tests/fixtures/terrain_dem_legacy.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        reader = module.load_terrain_dem
    else:
        extra = dict(diagnostics=record['stats'],window_observer=windows.append,
                     read_budget=TerrainReadBudget(tile_size=args.tile_size))
    start = time.perf_counter()
    try:
        grid, metadata = reader(args.dem,declaration,lon_deg=108.9,lat_deg=34.24,
                                radius_m=args.radius_m,resolution_m=60,geoid=geoid,**extra)
        record.update(load_seconds=time.perf_counter()-start,metadata=metadata,source_id=grid.source_id)
        start = time.perf_counter()
        np.save(args.output/'terrain.npy',grid.elevations_m,allow_pickle=False)
        record['buffered_write_seconds'] = time.perf_counter()-start
        record['reader_and_write_peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
        record['rss_under_512_mib'] = record['reader_and_write_peak_rss_bytes'] <= 512*1024**2
        start = time.perf_counter()
        record['output_sha256'] = checksum_sha256(args.output/'terrain.npy')
        record['output_hash_seconds'] = time.perf_counter()-start
        record['read_windows'] = windows
        record['unique_read_cells'] = window_union_cells(windows)
        record['repeated_read_cells'] = sum(w*h for _,_,w,h in windows)-record['unique_read_cells']
        if not record['rss_under_512_mib']:
            raise RuntimeError('observed RSS exceeds frozen validation budget')
        record['status'] = 'passed'
    except Exception as exc:
        record.update(status='failed',error=str(exc))
        raise
    finally:
        (args.output/'result.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:record[k] for k in ('mode','radius_m','status','reader_and_write_peak_rss_bytes')}))


if __name__ == '__main__':
    main()
