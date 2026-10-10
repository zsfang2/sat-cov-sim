"""Archive a small offline direction-table and cache verification run."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from satellite_coverage.engine.direction_table import CacheMismatch, DirectionTable, TerrainLocalSolver
from satellite_coverage.engine.terrain_context import TerrainContext
from satellite_coverage.geometry.terrain import TerrainGrid
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record


def run(output):
    record = RunRecord(output)
    root = Path(__file__).resolve().parents[1]
    try:
        record.write('environment.json', environment_record(root))
        archive_sources(root, record.path/'sources.zip')
        config = dict(azimuth_step_deg=30, elevations_deg=[0, 5, 10, 15, 20, 25, 30], frequency_hz=14.5e9,
                      slant_range_m=550000, radius_m=150, step_m=5, antenna_height_m=2,
                      query_directions=[[0, 5], [360, 5], [15, 7.5], [345, 7.5], [0, -1], [0, 45], [None, 90]],
                      scope='software verification only; held-out accuracy/cost experiment is separate')
        record.write('config.json', config)
        raster = np.zeros((41, 41))
        raster[10] = 42
        np.save(record.path/'grid.npy', raster)
        grid = TerrainGrid(raster, -205, 205, 10, 'WGS84_ellipsoid', 'synthetic-single-ridge', surface_type='synthetic')
        context = TerrainContext(grid, 0, 0, config['radius_m'], config['step_m'], effective_radius_m=6371000,
                                 sampling_method='cell_intervals')
        receiver = dict(lon_deg=0, lat_deg=0, antenna_ellipsoid_height_m=config['antenna_height_m'])
        solver = TerrainLocalSolver(context, receiver, frequency_hz=config['frequency_hz'], slant_range_m=config['slant_range_m'])
        start = time.perf_counter()
        table = DirectionTable.build(solver, azimuth_step_deg=config['azimuth_step_deg'], elevations_deg=config['elevations_deg'], chunk_size=16)
        build_s = time.perf_counter()-start
        cache = table.save(record.path)
        loaded = DirectionTable.load(cache, expected_descriptor=solver.descriptor())
        exact_errors = []
        for row in table.samples:
            actual = loaded.query(row['azimuth_deg'], row['elevation_deg'], expected_descriptor=solver.descriptor())
            assert actual['response'] == row['response']
            if row['response']['local_loss']['status'] == 'known':
                exact_errors.append(abs(actual['response']['local_loss']['value']-row['response']['local_loss']['value']))
        queries = []
        for method in ('nearest', 'bilinear'):
            for batch in loaded.query_batch(config['query_directions'], method=method, expected_descriptor=solver.descriptor(),
                                            fallback_solver=solver, chunk_size=3):
                queries.extend(dict(requested_method=method, **row) for row in batch)
        record.write('queries.json', queries)
        wrong = solver.descriptor()
        wrong['frequency_hz'] *= 2
        try:
            DirectionTable.load(cache, expected_descriptor=wrong)
        except CacheMismatch:
            stale_rejected = True
        else:
            raise AssertionError('stale frequency cache accepted')
        summary = dict(cache_key=table.cache_key, sample_count=len(table.samples), known_sample_count=len(exact_errors),
                       boundary_sample_count=sum(s['boundary'] for s in table.samples), max_sample_error_db=max(exact_errors),
                       cache_bytes=cache.stat().st_size, build_s=build_s, stale_cache_rejected=stale_rejected,
                       cache_file=cache.name, query_methods=[r['method'] for r in queries],
                       finite_scope=terrain_contract if (terrain_contract := table.samples[0]['response']['terrain_contract']) else None,
                       accuracy_claim='sample reproduction only; no held-out interpolation error bound')
        record.write('summary.json', summary)
        record.finish('passed', **summary)
        print(json.dumps(summary))
    except Exception as exc:
        record.finish('failed', error=str(exc))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
