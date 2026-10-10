"""Run frozen component/cache factors, held-out direction errors and cost."""

import argparse
from collections import Counter
from copy import deepcopy
import itertools
import json
from pathlib import Path
import time

import numpy as np
import yaml

from satellite_coverage.config.pilot import identity
from satellite_coverage.data_sources.manifest import checksum_sha256
from satellite_coverage.engine.direction_table import CacheMismatch, DirectionTable, TerrainLocalSolver
from satellite_coverage.engine.terrain_context import TerrainContext
from satellite_coverage.experiments.direction_cache import recompose, full_pipeline, check_pipeline, query_options, timings, break_even
from satellite_coverage.experiments.model_comparison import error_stats
from satellite_coverage.geometry.terrain import TerrainGrid
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record
from verify_model_comparison import write_csv


def load_scene(spec, root, record):
    if spec['id'] == 'flat_synthetic':
        grid = TerrainGrid(np.zeros((41, 41)), -205, 205, 10, 'WGS84_ellipsoid', 'synthetic:flat', surface_type='synthetic')
        np.save(record.path/'flat-grid.npy', grid.elevations_m)
        return grid, 0, 0, dict(kind='artificial', source_id=grid.source_id)
    source = root/spec['source_run']
    names = ['qinling_mountain-60-grid.npy', 'qinling_mountain-60-terrain.json']
    manifest = json.loads((source/'artifacts.json').read_text())
    for name in names:
        if checksum_sha256(source/name) != manifest['files'][name]:
            raise ValueError('real input checksum mismatch')
        (record.path/name).write_bytes((source/name).read_bytes())
    meta = json.loads((source/names[1]).read_text())
    array = np.load(source/names[0], allow_pickle=False)
    half = array.shape[0]*60/2
    grid = TerrainGrid(array, -half, half, 60, 'WGS84_ellipsoid', identity(meta), surface_type='DSM')
    return grid, meta['lon_deg'], meta['lat_deg'], dict(metadata=meta, hashes={n: manifest['files'][n] for n in names})


def negative_checks(table, solver):
    descriptor = solver.descriptor()
    checks = []
    mutations = [('frequency_hz', None, 1e9), ('receiver', 'antenna_ellipsoid_height_m', descriptor['receiver']['antenna_ellipsoid_height_m']+8),
                 ('system', 'slant_range_m', 551000), ('environment', 'radius_m', descriptor['environment']['radius_m']+1),
                 ('environment', 'step_m', descriptor['environment']['step_m']/2), ('environment', 'loss_cap_db', 30),
                 ('environment', 'effective_radius_m', None), ('environment', 'source_id', 'other-source'),
                 ('environment', 'grid_sha256', 'other-scene')]
    for section, field, value in mutations:
        changed = deepcopy(descriptor)
        if field is None:
            changed[section] = value
        else:
            changed[section][field] = value
        try:
            table.query(0, 5, expected_descriptor=changed)
        except CacheMismatch:
            checks.append(dict(field=f'{section}.{field}', rejected=True))
        else:
            raise AssertionError('stale cache incorrectly accepted')
    options = dict(expected_descriptor=descriptor, error_tolerance_db=1e-6)
    assert table.query(7.5, 2.5, **options)['method'] == 'fallback_required'
    assert table.query(7.5, 2.5, fallback_solver=solver, **options)['method'] == 'direct_fallback'
    assert table.query(0, 5, expected_descriptor=descriptor)['response'] == table.query(360, 5, expected_descriptor=descriptor)['response']
    assert table.query(0, 0, expected_descriptor=descriptor)['response']['local_loss']['status'] == 'not_applicable'
    assert table.query(0, -1, fallback_solver=solver, expected_descriptor=descriptor)['response']['local_loss']['status'] == 'not_applicable'
    return checks


def plots(path, errors, costs):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for method in ('nearest_raw_diagnostic', 'bilinear_raw_diagnostic', 'strict_fallback'):
        items = [r for r in errors if r['method'] == method]
        axes[0].plot(range(len(items)), [r['used_loss_error']['mae_db'] for r in items], 'o-', label=method)
    axes[0].set(xlabel='All frozen scene/frequency/height/grid groups', ylabel='Used-loss MAE (dB)')
    axes[0].legend(fontsize=7)
    ratios = [r['query']['median_s']/r['direct']['median_s'] for r in costs]
    axes[1].plot(ratios, '.')
    axes[1].axhline(1, color='black', linestyle='--')
    axes[1].set(xlabel='All frozen method groups', ylabel='Hot lookup / direct time', title='Below 1 is faster; compare accuracy separately')
    fig.savefig(path/'direction-error-cost.png', dpi=160)
    plt.close(fig)


def run(config_path, output):
    cfg = yaml.safe_load(config_path.read_text())
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads((root/'reports/m2/e1-design-sources.json').read_text())
    if checksum_sha256(config_path) != frozen['config_sha256']:
        raise ValueError('experiment config differs from pre-results freeze')
    record = RunRecord(output)
    try:
        record.write('environment.json', environment_record(root))
        record.write('config.json', cfg)
        archive_sources(root, record.path/'sources.zip')
        h = cfg['heldout']
        directions = list(itertools.product([h['azimuth_start_deg']+i*h['azimuth_step_deg'] for i in range(h['azimuth_count'])],
                                             [h['elevation_start_deg']+i*h['elevation_step_deg'] for i in range(h['elevation_count'])]))
        factor_rows, heldout_rows, costs, errors, inputs, negatives = [], [], [], [], [], []
        cache_records = []
        for scene in cfg['scenes']:
            grid, lon, lat, evidence = load_scene(scene, root, record)
            ground, status = grid.sample(0, 0)
            if status != 'known':
                raise ValueError('receiver ground missing')
            inputs.append(dict(scene_id=scene['id'], ground_ellipsoid_height_m=ground, **evidence))
            providers, tables = {}, {}
            for frequency, height in itertools.product(cfg['frequency_hz'], cfg['height_agl_m']):
                context = TerrainContext(grid, lon, lat, scene['radius_m'], scene['step_m'], cfg['effective_radius_m'],
                                         cfg['loss_cap_db'], sampling_method='cell_intervals')
                receiver = dict(lon_deg=lon, lat_deg=lat, antenna_ellipsoid_height_m=ground+height)
                started = time.perf_counter()
                solver = TerrainLocalSolver(context, receiver, frequency_hz=frequency, slant_range_m=cfg['slant_range_m'])
                initialize_s = time.perf_counter()-started
                providers[frequency, height] = solver, context, receiver
                direct = [solver.evaluate(*d) for d in directions]
                direct_time = timings(lambda: [solver.evaluate(*d) for d in directions], cfg['hot_repeats'])
                for spacing in cfg['azimuth_steps_deg']:
                    started = time.perf_counter()
                    table = DirectionTable.build(solver, azimuth_step_deg=spacing, elevations_deg=cfg['elevations_deg'])
                    build_s = time.perf_counter()-started
                    started = time.perf_counter()
                    path = table.save(record.path)
                    save_s = time.perf_counter()-started
                    started = time.perf_counter()
                    table = DirectionTable.load(path, expected_descriptor=solver.descriptor())
                    reload_s = time.perf_counter()-started
                    tables[frequency, height, spacing] = table
                    cache_records.append(dict(scene=scene['id'], frequency_hz=frequency, height_agl_m=height, spacing_deg=spacing,
                                              key=table.cache_key, file=path.name, samples=len(table.samples), bytes=path.stat().st_size,
                                              initialize_s=initialize_s, build_s=build_s, save_s=save_s, reload_s=reload_s))
                    assert not set(directions).intersection((s['azimuth_deg'], s['elevation_deg']) for s in table.samples)
                    if frequency == cfg['baseline']['frequency_hz'] and height == cfg['baseline']['height_agl_m']:
                        negatives.extend(dict(scene=scene['id'], spacing_deg=spacing, **n) for n in negative_checks(table, solver))
                    for method in cfg['methods']:
                        options = query_options(method, solver, cfg['exact_recomposition_tolerance_db'])
                        query_time = timings(lambda: [table.query(*d, **options) for d in directions], cfg['hot_repeats'])
                        queries = [table.query(*d, **options) for d in directions]
                        group = []
                        for direction, reference, query in zip(directions, direct, queries):
                            actual = query['response']
                            known = reference['local_loss']['status'] == actual['local_loss']['status'] == 'known'
                            params = dict(cfg['baseline'], frequency_hz=frequency, height_agl_m=height,
                                          azimuth_deg=direction[0], elevation_deg=direction[1])
                            db, qb = recompose(reference, params, cfg), recompose(actual, params, cfg)
                            row = dict(scene=scene['id'], frequency_hz=frequency, height_agl_m=height, spacing_deg=spacing,
                                       method=method, direction=direction, cache_key=table.cache_key, direct=reference, query=query,
                                       paired_known=known, capped=reference['cap_triggered'] or actual['cap_triggered'],
                                       raw_error_db=actual['raw_loss_db']-reference['raw_loss_db'] if known else None,
                                       used_error_db=actual['local_loss']['value']-reference['local_loss']['value'] if known else None,
                                       power_error_db=qb['received_power']['value']-db['received_power']['value'] if known else None,
                                       status_equal=reference['local_loss']['status'] == actual['local_loss']['status'],
                                       visibility_equal=reference['visibility'] == actual['visibility'])
                            if method == 'strict_fallback':
                                assert query['method'] == 'direct_fallback' and row['status_equal']
                                assert not known or max(abs(row[k]) for k in ('raw_error_db', 'used_error_db', 'power_error_db')) <= cfg['exact_recomposition_tolerance_db']
                            group.append(row)
                        heldout_rows.extend(group)
                        common = dict(scene=scene['id'], frequency_hz=frequency, height_agl_m=height, spacing_deg=spacing, method=method)
                        fallback_count = sum(q['method'] == 'direct_fallback' for q in queries)
                        costs.append(dict(**common, query=query_time, direct=direct_time, initialize_s=initialize_s, build_s=build_s,
                                          save_s=save_s, reload_s=reload_s, count=len(directions), fallback_count=fallback_count,
                                          build_break_even=break_even(build_s+initialize_s, direct_time['median_s']/len(directions), query_time['median_s']/len(directions)),
                                          reload_break_even=break_even(reload_s, direct_time['median_s']/len(directions), query_time['median_s']/len(directions))))
                        errors.append(dict(**common, total=len(group), known=sum(r['paired_known'] for r in group),
                                           capped=sum(r['capped'] for r in group), fallback_count=fallback_count,
                                           direct_statuses=dict(Counter(r['direct']['local_loss']['status'] for r in group)),
                                           query_statuses=dict(Counter(r['query']['response']['local_loss']['status'] for r in group)),
                                           status_mismatch=sum(not r['status_equal'] for r in group), visibility_mismatch=sum(not r['visibility_equal'] for r in group),
                                           raw_loss_error=error_stats([r['raw_error_db'] for r in group if r['paired_known']]),
                                           used_loss_error=error_stats([r['used_error_db'] for r in group if r['paired_known']]),
                                           approximate_only_used_error=error_stats([r['used_error_db'] for r in group if r['paired_known'] and r['query']['method'] in ('nearest', 'bilinear')]),
                                           uncapped_used_error=error_stats([r['used_error_db'] for r in group if r['paired_known'] and not r['capped']]),
                                           power_error=error_stats([r['power_error_db'] for r in group if r['paired_known']])))
            for case in cfg['factor_cases']:
                params = dict(cfg['baseline'], **{k: v for k, v in case.items() if k != 'id'})
                solver, context, receiver = providers[params['frequency_hz'], params['height_agl_m']]
                direct = solver.evaluate(params['azimuth_deg'], params['elevation_deg'])
                budget = recompose(direct, params, cfg)
                pipeline = full_pipeline(context, receiver, params, cfg)
                assert all(check_pipeline(r, direct, budget, params, cfg) for r in pipeline['records'])
                record.write(f"{scene['id']}-{case['id']}-m1.json", pipeline)
                for spacing, method in itertools.product(cfg['azimuth_steps_deg'], cfg['methods']):
                    table = tables[params['frequency_hz'], params['height_agl_m'], spacing]
                    query = table.query(params['azimuth_deg'], params['elevation_deg'], **query_options(method, solver, cfg['exact_recomposition_tolerance_db']))
                    composed = recompose(query['response'], params, cfg)
                    a, b = budget['received_power'], composed['received_power']
                    error = b['value']-a['value'] if a['status'] == b['status'] == 'known' else None
                    if method == 'strict_fallback' or query['method'] == 'sample':
                        assert a['status'] == b['status'] and (error is None or abs(error) <= cfg['exact_recomposition_tolerance_db'])
                    factor_rows.append(dict(scene=scene['id'], case=case['id'], parameters=params, spacing_deg=spacing, method=method,
                                            cache_key=table.cache_key, direct=direct, query=query, direct_budget=budget,
                                            cached_budget=composed, power_error_db=error, m1_crosscheck=True))
            print(f"{scene['id']} completed: {len(factor_rows)} factor rows, {len(heldout_rows)} held-out rows", flush=True)
        for name, value in [('inputs', inputs), ('factors', factor_rows), ('errors', errors), ('costs', costs),
                             ('caches', cache_records), ('negative-checks', negatives)]:
            record.write(name+'.json', value)
            if name in ('errors', 'costs', 'caches', 'negative-checks'):
                write_csv(record.path/(name+'.csv'), value)
        factor_table = []
        for row in factor_rows:
            original = next(r for r in factor_rows if r['scene'] == row['scene'] and r['case'] == 'baseline'
                            and r['spacing_deg'] == row['spacing_deg'] and r['method'] == row['method'])
            base_components = {c['name']: c['quantity']['value'] for c in original['direct_budget']['components']}
            component_changes = {c['name']: c['quantity']['value'] != base_components[c['name']] for c in row['direct_budget']['components']}
            factor_table.append(dict(scene=row['scene'], case=row['case'], spacing_deg=row['spacing_deg'], method=row['method'],
                                     parameters=row['parameters'], same_local_cache_key=row['cache_key'] == original['cache_key'],
                                     changed_components=component_changes, direct_raw_loss_db=row['direct']['raw_loss_db'],
                                     queried_raw_loss_db=row['query']['response']['raw_loss_db'],
                                     direct_used_loss_db=row['direct']['local_loss']['value'],
                                     queried_used_loss_db=row['query']['response']['local_loss']['value'],
                                     direct_gain_dbi=row['direct_budget']['receiver_gain_dbi'],
                                     direct_power_dbm=row['direct_budget']['received_power']['value'],
                                     query_method=row['query']['method'], power_error_db=row['power_error_db'],
                                     direct_cap=row['direct']['cap_triggered'], query_cap=row['query']['response']['cap_triggered'],
                                     m1_crosscheck=row['m1_crosscheck']))
        write_csv(record.path/'factors.csv', factor_table)
        with (record.path/'heldout.jsonl').open('w') as stream:
            for row in heldout_rows:
                stream.write(json.dumps(row, allow_nan=False)+'\n')
        summary = dict(factor_rows=len(factor_rows), heldout_rows=len(heldout_rows), tables=len(cache_records),
                       strict_max_power_error_db=max(abs(r['power_error_db']) for r in factor_rows if r['method'] == 'strict_fallback' and r['power_error_db'] is not None),
                       negative_identity_checks=len(negatives), m1_pipeline_cases=len(cfg['scenes'])*len(cfg['factor_cases']),
                       break_even_statuses=dict(Counter(r['build_break_even']['status'] for r in costs)),
                       errors=errors, costs=costs, physics_scope='same finite-radius local model; no measurement truth or business error bound')
        record.write('summary.json', summary)
        plots(record.path, errors, costs)
        record.finish('passed', tables=len(cache_records), factor_rows=len(factor_rows), heldout_rows=len(heldout_rows),
                      strict_max_power_error_db=summary['strict_max_power_error_db'], m1_pipeline_cases=summary['m1_pipeline_cases'])
        print(json.dumps({k:v for k,v in summary.items() if k not in ('errors','costs')}))
    except Exception as exc:
        record.finish('failed', error=str(exc))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/m2_e1.yaml'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.config, args.output)
