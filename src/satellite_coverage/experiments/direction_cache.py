"""Local-cache recomposition against the actual scalar link pipeline."""

import math
import statistics
import time

from ..engine.link_budget import compose_budget
from ..engine.links import calculate_links
from ..geometry.antenna import receive_gain
from ..geometry.local import direction_to_enu


def query_options(method, solver, tolerance_db):
    return dict(method='nearest' if method == 'nearest_raw_diagnostic' else 'bilinear',
                expected_descriptor=solver.descriptor(), fallback_solver=solver,
                error_tolerance_db=tolerance_db if method == 'strict_fallback' else None)


def recompose(response, parameters, config):
    geometry = dict(slant_range_m=config['slant_range_m'],
                    geometrically_above_local_horizontal=parameters['elevation_deg'] > 0)
    enu = direction_to_enu(azimuth_deg=parameters['azimuth_deg'], elevation_deg=parameters['elevation_deg'],
                           slant_range_m=config['slant_range_m'])
    antenna = config['antenna_models'][parameters['antenna']]
    gain = receive_gain(antenna, enu)
    losses = dict(atmosphere=dict(value=config['atmosphere_loss_db'], status='known', reason=config['atmosphere_basis']),
                  local={k: response['local_loss'][k] for k in ('value', 'status', 'reason')},
                  misc=dict(value=0.0, status='known', reason='declared_zero'))
    result = compose_budget(geometry, parameters['frequency_hz'], dict(mode='eirp', eirp_dbm=parameters['eirp_dbm']),
                            gain['gain_dbi'], losses, dict(received_power_dbm=config['threshold_dbm'], basis=config['threshold_basis']))
    result['receiver_antenna'] = gain
    return result


def full_pipeline(context, receiver, parameters, config):
    direction = {k: parameters[k] for k in ('azimuth_deg', 'elevation_deg')}
    direction['slant_range_m'] = config['slant_range_m']
    request = dict(schema_version=1, experiment_id='component-recomposition',
                   start='2025-01-01T00:00:00Z', end='2025-01-01T00:00:01Z', step_s=1,
                   receiver=dict(lon_deg=receiver['lon_deg'], lat_deg=receiver['lat_deg'], height_basis='ellipsoid',
                                 antenna_ellipsoid_height_m=receiver['antenna_ellipsoid_height_m'], basis='declared DEM ellipsoid ground plus AGL'),
                   source=dict(mode='direction_sequence', candidate_id='synthetic-direction', directions=[direction, direction]),
                   budget=dict(frequency_hz=parameters['frequency_hz'], power=dict(mode='eirp', eirp_dbm=parameters['eirp_dbm']),
                               receiver_antenna=config['antenna_models'][parameters['antenna']],
                               losses=dict(atmosphere=dict(enabled=True, value=config['atmosphere_loss_db'], status='known', reason=config['atmosphere_basis']),
                                           local=dict(enabled=False, reason='terrain context supplies local effect'),
                                           misc=dict(enabled=False, reason='declared zero')),
                               threshold=dict(received_power_dbm=config['threshold_dbm'], basis=config['threshold_basis']), assumption_basis='frozen scalar component experiment'))
    return calculate_links(request, terrain=context)


def check_pipeline(record, response, budget, parameters, config):
    tolerance = config['exact_recomposition_tolerance_db']
    geometry = record['geometry']
    for name in ('azimuth_deg', 'elevation_deg'):
        if not math.isclose(geometry[name], parameters[name], abs_tol=1e-9, rel_tol=0):
            raise AssertionError('geometry crosscheck failed')
    if not math.isclose(geometry['slant_range_m'], config['slant_range_m'], abs_tol=1e-6, rel_tol=0):
        raise AssertionError('range crosscheck failed')
    local = record['terrain']
    if local['loss_status'] != response['local_loss']['status'] or local['cap_triggered'] != response['cap_triggered']:
        raise AssertionError('local state crosscheck failed')
    for a, b in ((local['raw_loss_db'], response['raw_loss_db']), (local['used_loss_db'], response['local_loss']['value']),
                 (record['budget']['receiver_gain_dbi'], budget['receiver_gain_dbi'])):
        if (a is None) != (b is None) or (a is not None and abs(a-b) > tolerance):
            raise AssertionError('local/gain crosscheck failed')
    expected = {c['name']: c['quantity'] for c in record['budget']['components']}
    for component in budget['components']:
        a, b = component['quantity'], expected[component['name']]
        if a['status'] != b['status'] or (a['value'] is not None and abs(a['value']-b['value']) > tolerance):
            raise AssertionError('component crosscheck failed')
    for name in ('received_power', 'margin'):
        a, b = record['budget'][name], budget[name]
        if a['status'] != b['status'] or (a['value'] is not None and abs(a['value']-b['value']) > tolerance):
            raise AssertionError('power/margin crosscheck failed')
    return True


def timings(operation, repeats):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        operation()
        samples.append(time.perf_counter()-start)
    return dict(repeats_s=samples, median_s=statistics.median(samples), min_s=min(samples), max_s=max(samples))


def break_even(preparation_s, direct_per_query_s, cached_per_query_s):
    if cached_per_query_s >= direct_per_query_s:
        return dict(status='no_finite_break_even', queries=None)
    return dict(status='finite', queries=math.ceil(preparation_s/(direct_per_query_s-cached_per_query_s)))
