"""Measure the existing reader without changing its numerical implementation.

Run each radius in a fresh process. RSS is Linux resident memory; tracemalloc
does not capture every native allocation. File writes are buffered, not fsync.
"""

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
import tracemalloc

import numpy as np
import rasterio
import pyproj

from satellite_coverage.data_sources.terrain_dem import load_terrain_dem
from satellite_coverage.data_sources.manifest import checksum_sha256


def rss_bytes():
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmRSS:'):
            return int(line.split()[1]) * 1024
    raise RuntimeError('Linux VmRSS unavailable')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--radius-m', required=True, type=float)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    dem = root.parent / 'Satellite-Ground-Radiomap/data/l2_topo/china_dem_30.tif'
    geoid_path = root / 'output/geoid/egm2008-complete.tif'
    evidence = json.loads((root / 'reports/m3/copernicus-source.json').read_text())
    geoid_evidence = json.loads((root / 'reports/m3/egm2008-grid.json').read_text())
    declaration = dict(sha256=evidence['local_sha256'], height_unit='m',
                       vertical_datum='EGM2008', surface_type='DSM',
                       evidence=evidence['source_assessment'])
    geoid = dict(path=str(geoid_path), sha256=geoid_evidence['sha256'],
                 model='EGM2008', evidence=geoid_evidence['url'])
    source, first = inspect.getsourcelines(load_terrain_dem)
    markers = {
        'digest = checksum_sha256(path)': 'dem_hash',
        'local = CRS.from_proj4': 'target_coordinates',
        'with rasterio.Env': 'source_coordinates_and_checks',
        'values = src.read': 'source_window_read',
        'scale, offset =': 'sample_target',
        'if vertical is not None:': 'vertical_conversion',
        'if np.isinf(target).any():': 'metadata',
        'source_id = identity(metadata)': 'freeze_grid',
    }
    starts = {}
    for index, line in enumerate(source, first):
        for prefix, name in markers.items():
            if line.strip().startswith(prefix):
                starts[index] = name
    if set(starts.values()) != set(markers.values()):
        raise RuntimeError('Reader changed: recheck instrumentation markers')
    stages = []
    current = None
    baseline = rss_bytes()
    baseline_high_water = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    tracemalloc.start()

    def change(name):
        nonlocal current
        now = time.perf_counter()
        resident = rss_bytes()
        if current is not None:
            current.update(seconds=now-current.pop('start'), rss_end_bytes=resident,
                           traced_peak_bytes=tracemalloc.get_traced_memory()[1])
            stages.append(current)
        tracemalloc.reset_peak()
        current = dict(stage=name, start=now, rss_start_bytes=resident)

    def trace(frame, event, arg):
        if frame.f_code is not load_terrain_dem.__code__:
            return None
        if event == 'line' and frame.f_lineno in starts:
            change(starts.pop(frame.f_lineno))
        return trace

    change('validation_and_geoid_hash_setup')
    sys.settrace(trace)
    try:
        grid, metadata = load_terrain_dem(dem, declaration, lon_deg=108.9,
                                         lat_deg=34.24, radius_m=args.radius_m,
                                         resolution_m=60, geoid=geoid)
    finally:
        sys.settrace(None)
    change('buffered_npy_write')
    output = args.output / 'terrain.npy'
    np.save(output, grid.elevations_m, allow_pickle=False)
    change('output_hash')
    output_digest = checksum_sha256(output)
    change('finished')
    tracemalloc.stop()
    with rasterio.open(dem) as src:
        storage = dict(block_shapes=src.block_shapes, dtype=src.dtypes[0])
    record = dict(
        radius_m=args.radius_m, resolution_m=60, site=[108.9, 34.24],
        baseline_rss_bytes=baseline,
        baseline_high_water_rss_bytes=baseline_high_water,
        process_high_water_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        stages=stages, terrain_metadata=metadata, source_storage=storage,
        output_bytes=output.stat().st_size, output_sha256=output_digest,
        versions=dict(python=platform.python_version(), numpy=np.__version__,
                      rasterio=rasterio.__version__, pyproj=pyproj.__version__,
                      gdal=rasterio.__gdal_version__, proj=pyproj.proj_version_str),
        machine=dict(platform=platform.platform(),
                     meminfo=Path('/proc/meminfo').read_text().splitlines()[:3]),
        commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
        reader_sha256=hashlib.sha256(''.join(source).encode()).hexdigest(),
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        caveats=['Single instrumented run, not throughput SLA; OS page cache uncontrolled',
                 'Stage RSS endpoints are not per-stage peaks; process high water includes imports',
                 'tracemalloc excludes some native memory; phase overhead is included',
                 'Input hashes verified by original reader; output write is buffered'])
    (args.output / 'measurement.json').write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps({k: record[k] for k in ('radius_m', 'baseline_rss_bytes',
                                           'process_high_water_rss_bytes')}))


if __name__ == '__main__':
    main()
