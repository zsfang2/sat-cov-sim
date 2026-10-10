"""Execute the frozen three-role terrain experiment and archive all outcomes."""

import argparse
from collections import Counter
import csv
import itertools
import json
import math
from pathlib import Path
import time

import numpy as np
import yaml

from satellite_coverage.config.pilot import identity
from satellite_coverage.data_sources.manifest import checksum_sha256
from satellite_coverage.engine.model_comparison import ROLES, common_budget, compare_models
from satellite_coverage.engine.multi_edge import solve_edges
from satellite_coverage.engine.terrain_context import TerrainContext
from satellite_coverage.engine.terrain_link import evaluate_profile
from satellite_coverage.experiments.model_comparison import classify_refinements, summarize
from satellite_coverage.geometry.terrain import TerrainGrid
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record


def write_csv(path, records):
    with path.open('w', newline='') as stream:
        if not records:
            return
        fields = list(dict.fromkeys(k for r in records for k in r))
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in records)


def make_synthetic(scene, cfg):
    grid = np.zeros(cfg['raster_shape'])
    if scene in ('single_ridge', 'double_ridge', 'deep_ridge'):
        grid[10] = 502 if scene == 'deep_ridge' else 42
    if scene == 'double_ridge':
        grid[7] = 72
    if scene == 'terrace':
        grid[8:13] = 22
    if scene == 'nodata':
        grid[10] = np.nan
    if scene == 'receiver_nodata':
        grid[20, 20] = np.nan
    return TerrainGrid(grid, cfg['west_m'], cfg['north_m'], cfg['resolution_m'],
                       'WGS84_ellipsoid', 'synthetic:'+scene, surface_type='synthetic')


def discrete_cases(frequency_hz):
    """Common explicit point lists isolate edge accumulation from raster sampling."""
    cases = [('single_edge', [(500, 20)], 1000, frequency_hz),
             ('double_edge', [(250, 20), (750, 20)], 1000, frequency_hz),
             ('ntia_table_2', [(1200, 140), (2800, 260), (4400, 200), (5800, 220)], 6600, 1.5e9)]
    results = []
    for name, points, length, freq in cases:
        profile = dict(samples=[dict(distance_m=x, relative_height_m=h) for x, h in points],
                       radius_m=max(x for x, _ in points), incomplete_reasons=[])
        single = evaluate_profile(profile, elevation_deg=0, slant_range_m=length, frequency_hz=freq)
        multi = solve_edges(points, length_m=length, frequency_hz=freq)
        horizon = max(math.degrees(math.atan2(h, x)) for x, h in points)
        results.append(dict(case=name, points_m=points, frequency_hz=freq, length_m=length,
                            evidence_level='V0', sky=dict(horizon_deg=horizon, visibility='blocked', local_loss=None),
                            single=single, multi=multi, source='NTIA TR-26-580 table 2' if name.startswith('ntia') else 'analytic constructed geometry'))
    return results


def figures(path, summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    valid = [r for r in summary['differences'] if r['paired_known']]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for capped, marker in ((False, '.'), (True, 'x')):
        items = [r for r in valid if r['capped'] == capped]
        axes[0].scatter([r['current_raw_loss_db'] for r in items], [r['reference_raw_loss_db'] for r in items],
                        s=14, marker=marker, label='capped' if capped else 'uncapped', alpha=.5)
    axes[0].set(xlabel='Single-edge raw loss (dB)', ylabel='Multi-edge raw loss (dB)')
    axes[0].legend()
    axes[1].hist([r['raw_difference_db'] for r in valid], bins=40)
    axes[1].set(xlabel='Multi minus single raw loss (dB)', ylabel='All known pairs')
    fig.suptitle('Finite-radius model comparison; not measurement error')
    fig.savefig(path/'raw-loss-comparison.png', dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4), constrained_layout=True)
    t = summary['thresholds']
    ax.plot([r['offset_db'] for r in t], [r['disagreements']/r['known'] if r['known'] else np.nan for r in t], 'o-')
    ax.set(xlabel='Hypothetical offset from unobstructed power (dB)', ylabel='Disagreement / known pairs', ylim=(-.02, 1.02))
    ax.set_title('Unknown pairs excluded from ratio and reported separately')
    fig.savefig(path/'threshold-disagreement.png', dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4), constrained_layout=True)
    ax.bar(['sky', 'single edge', 'multi edge'], [r['solver_wall_s'] for r in summary['roles']])
    ax.set(ylabel='Total adapter/solver time (s)', title='Shared preparation excluded; process RSS is shared')
    fig.savefig(path/'role-cost.png', dpi=160)
    plt.close(fig)


def run(config_path, output):
    cfg = yaml.safe_load(config_path.read_text())
    if cfg['roles'] != list(ROLES):
        raise ValueError('configuration must request the three frozen roles')
    record = RunRecord(output)
    root = Path(__file__).resolve().parents[1]
    try:
        env = environment_record(root)
        record.write('environment.json', env)
        record.write('config.json', cfg)
        (record.path/'config.yaml').write_bytes(config_path.read_bytes())
        archive_sources(root, record.path/'sources.zip')
        provenance = {k: env[k] for k in ('code_commit', 'source_fingerprint')}
        rows, rejected, inputs = [], [], []
        preparation_s = 0
        seen = set()
        limits = {k: cfg['reference'][k] for k in ('maximum_points', 'maximum_depth', 'maximum_nodes')}
        baseline = cfg['baseline']
        with (record.path/'profiles.jsonl').open('w') as profiles:
            def query(grid, scene, lon, lat, native, step, az, el, *, overrides=None, radius=None, case='baseline', custom_limits=None):
                nonlocal preparation_s
                parameters = dict(baseline, **(overrides or {}))
                key = identity(dict(scene=scene, step=step, az=az, el=el, parameters=parameters, radius=radius, limits=custom_limits))
                if key in seen:
                    return
                seen.add(key)
                context = TerrainContext(grid, lon, lat, radius, step, parameters['effective_radius_m'],
                                         parameters['loss_cap_db'], sampling_method='cell_intervals')
                ground, _ = grid.sample(0, 0)
                receiver = dict(lon_deg=lon, lat_deg=lat,
                                antenna_ellipsoid_height_m=(ground or 0)+parameters['height_above_surface_m'])
                geometry = dict(azimuth_deg=None if el == 90 else az, elevation_deg=el,
                                slant_range_m=parameters['slant_range_m'], frequency_hz=parameters['frequency_hz'],
                                geometrically_above_local_horizontal=el > 0)
                meta = dict(sample_id=f'{az}:{el}', candidate_id=scene, scene_id=scene, timestamp_utc=None,
                            pass_id=None, satellite_id=None, config_hash=identity(cfg), native_spacing_m=native)
                try:
                    budget = common_budget(frequency_hz=parameters['frequency_hz'], slant_range_m=parameters['slant_range_m'],
                                           eirp_dbm=parameters['eirp_dbm'], receiver_gain_dbi=parameters['receiver_gain_dbi'],
                                           nonlocal_losses_db=parameters['nonlocal_losses_db'],
                                           threshold_offsets_db=cfg['threshold_offsets_from_unobstructed_power_db'])
                    batch, evidence = compare_models(context, geometry, receiver, budget, metadata=meta,
                                                     provenance=provenance, reference_limits=custom_limits or limits)
                except (ValueError, ArithmeticError) as exc:
                    rejected.append(dict(request_id=key, scene_id=scene, case=case, parameters=parameters,
                                         geometry=geometry, receiver=receiver, terrain=context.descriptor(),
                                         status='failed', failure_kind='invalid_input', reasons=[str(exc)],
                                         requested_roles=list(ROLES), comparison_eligible=False))
                    return
                for row in batch:
                    row['experiment'] = dict(case=case, null_metadata_reason='artificial_direction_not_a_TLE_pass',
                                             input_surface='synthetic' if grid.surface_type == 'synthetic' else 'Copernicus DSM, declared EGM2008 converted to ellipsoid')
                rows.extend(batch)
                if evidence is not None:
                    profiles.write(json.dumps(dict(pair_id=batch[0]['identity']['pair_id'], **evidence), allow_nan=False)+'\n')
                preparation_s += batch[0]['resources']['shared_preparation_time_s']
            syn = cfg['synthetic']
            for scene in syn['scenes']:
                grid = make_synthetic(scene, syn)
                np.save(record.path/f'{scene}-grid.npy', grid.elevations_m)
                for step, az, el in itertools.product(syn['steps_m'], baseline['azimuths_deg'], baseline['elevations_deg']):
                    query(grid, scene, 0, 0, syn['resolution_m'], step, az, el, radius=syn['radius_m'])
                for factor, values in cfg['one_factor_sweeps'].items():
                    if factor == 'scope':
                        continue
                    for value, step, el in itertools.product(values, syn['steps_m'], [1, 5, 30]):
                        override = {} if factor == 'synthetic_radius_m' else {factor: value}
                        query(grid, scene, 0, 0, syn['resolution_m'], step, 0, el, overrides=override,
                              radius=value if factor == 'synthetic_radius_m' else syn['radius_m'], case='one_factor:'+factor)
                print(f'synthetic {scene} complete, {len(rows)} rows', flush=True)
            for case in syn['special_cases']:
                grid = make_synthetic(case, syn)
                overrides, el, radius, custom = {}, 5, syn['radius_m'], None
                if case == 'outside_dem':
                    radius = 300
                elif case == 'below_horizon':
                    el = -1
                elif case == 'zenith':
                    el = 90
                elif case == 'near_transmitter':
                    overrides['slant_range_m'] = 100
                elif case == 'invalid_frequency':
                    overrides['frequency_hz'] = 0
                elif case == 'resource_refusal':
                    custom = dict(limits, maximum_points=1)
                query(grid, case, 0, 0, syn['resolution_m'], 5, 0, el, radius=radius,
                      overrides=overrides, custom_limits=custom, case='special:'+case)
            real = cfg['real']
            source = root/real['source_run']
            manifest_path = source/'artifacts.json'
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
            for site in real['sites']:
                names = [f'{site}-60-grid.npy', f'{site}-60-terrain.json']
                if manifest is None or any(not (source/name).exists() for name in names):
                    rejected.append(dict(scene_id=site, status='not_computed', failure_kind='missing_input',
                                         requested_roles=list(ROLES), comparison_eligible=False))
                    continue
                for name in names:
                    actual = checksum_sha256(source/name)
                    if actual != manifest['files'][name]:
                        raise ValueError(f'source artifact checksum mismatch: {name}')
                    inputs.append(dict(path=str(source/name), sha256=actual,
                                       manifest_sha256=checksum_sha256(manifest_path)))
                    (record.path/name).write_bytes((source/name).read_bytes())
                meta = json.loads((source/names[1]).read_text())
                array = np.load(source/names[0], allow_pickle=False)
                half = array.shape[0]*real['grid_resolution_m']/2
                grid = TerrainGrid(array, -half, half, real['grid_resolution_m'], 'WGS84_ellipsoid', identity(meta),
                                   surface_type=meta['declaration']['surface_type'])
                for step, height, az, el in itertools.product(real['steps_m'], real['heights_above_surface_m'],
                                                              baseline['azimuths_deg'], real['elevations_deg']):
                    query(grid, site, meta['lon_deg'], meta['lat_deg'], meta['estimated_native_spacing_max_m'],
                          step, az, el, radius=real['radius_m'], overrides=dict(height_above_surface_m=height), case='real')
                print(f'real {site} complete, {len(rows)} rows', flush=True)
        refinement = classify_refinements(rows, cfg['reference']['convergence_raw_loss_db'])
        summary = summarize(rows)
        summary['rejected_request_count'] = len(rejected)
        summary['shared_preparation_s'] = preparation_s
        record.write('inputs.json', inputs)
        record.write('rejected-requests.json', rejected)
        record.write('refinements.json', refinement)
        record.write('discrete-cases.json', discrete_cases(baseline['frequency_hz']))
        record.write('summary.json', summary)
        with (record.path/'roles.jsonl').open('w') as stream:
            for row in rows:
                stream.write(json.dumps(row, allow_nan=False)+'\n')
        for name, values in [('groups', summary['groups']), ('differences', summary['differences']),
                             ('thresholds', summary['thresholds']), ('threshold-details', summary['threshold_details']),
                             ('visibility', summary['visibility']), ('caps', summary['capped_pairs']),
                             ('failures', summary['failures']), ('refinements', refinement), ('role-resources', summary['roles'])]:
            write_csv(record.path/f'{name}.csv', values)
        figures(record.path, summary)
        expected_rejections = [r for r in rejected if r.get('scene_id') == 'invalid_frequency' and r['failure_kind'] == 'invalid_input']
        unexpected = len(rejected)-len(expected_rejections)
        record.finish('passed' if unexpected == 0 else 'incomplete', pair_count=summary['pair_count'],
                      row_count=summary['row_count'], rejected_request_count=len(rejected),
                      unexpected_rejections=unexpected, real_inputs_verified=len(inputs),
                      reference_eligibility=dict(Counter(r['model']['reference_eligibility'] for r in rows if r['model']['role_id'] == ROLES[2])),
                      scope='software experiment completed; not a physical accuracy acceptance')
        print(json.dumps(dict(output=str(record.path), pairs=summary['pair_count'], rejected=len(rejected))))
    except Exception as exc:
        record.finish('failed', error=str(exc))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/m4_e2.yaml'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.config, args.output)
