"""Three-role finite-terrain comparisons with explicit common input binding."""

from copy import deepcopy
from datetime import datetime
import math
import resource
import time

from ..config.pilot import identity
from ..domain.link_record import Quantity, QuantityStatus, LossComponent, compose_received_power
from ..geometry.cell_horizon import cell_horizon
from ..geometry.cell_profile import cell_profile
from .interval_extrema import loss_extrema
from .link_budget import free_space_loss_db
from .multi_edge import ResourceLimit, solve_edges
from .terrain_contract import terrain_scope

ROLES = ('sky_horizon_outline_v1', 'm3_current_single_edge_v1', 'reference_multi_edge_deygout_v1')
NONLOCAL = ('free_space', 'gas', 'rain', 'clutter', 'other')


def quantity(value, unit, status, reason):
    return Quantity(value, unit, QuantityStatus(status), reason).to_mapping()


def finite(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    if positive and value <= 0:
        raise ValueError(f'{name} must be positive')


def common_budget(*, frequency_hz, slant_range_m, eirp_dbm, receiver_gain_dbi,
                  nonlocal_losses_db, threshold_offsets_db):
    for name, value in (('frequency_hz', frequency_hz), ('slant_range_m', slant_range_m)):
        finite(value, name, positive=True)
    finite(eirp_dbm, 'eirp_dbm')
    finite(receiver_gain_dbi, 'receiver_gain_dbi')
    if set(nonlocal_losses_db) != set(NONLOCAL)-{'free_space'}:
        raise ValueError('nonlocal losses must declare exactly gas/rain/clutter/other')
    values = dict(free_space=free_space_loss_db(slant_range_m, frequency_hz), **nonlocal_losses_db)
    components = []
    for name in NONLOCAL:
        value = values[name]
        finite(value, name)
        components.append(dict(name=name, quantity=quantity(value, 'dB', 'known', 'declared_common_budget'),
                               effects=[name], solver='free_space' if name == 'free_space' else 'declared_scalar'))
    if not threshold_offsets_db or len(set(threshold_offsets_db)) != len(threshold_offsets_db):
        raise ValueError('threshold offsets must be nonempty and unique')
    for offset in threshold_offsets_db:
        finite(offset, 'threshold offset')
    return dict(frequency_hz=frequency_hz, power_mode='eirp', eirp_dbm=eirp_dbm,
                transmit_power_dbm=None, transmit_gain_dbi=None, receiver_gain_dbi=receiver_gain_dbi,
                antenna_model_id='isotropic', pointing=None,
                mean_power_definition='scalar_mean_power_no_fast_fading', nonlocal_components=components,
                threshold_offsets_db=list(threshold_offsets_db))


def components_from(budget):
    if (budget['power_mode'] != 'eirp' or budget['transmit_power_dbm'] is not None
            or budget['transmit_gain_dbi'] is not None or budget['antenna_model_id'] != 'isotropic'
            or budget['pointing'] is not None or budget['mean_power_definition'] != 'scalar_mean_power_no_fast_fading'):
        raise ValueError('unsupported power/antenna/mean-power contract')
    components = []
    for c in budget['nonlocal_components']:
        q = c['quantity']
        if q['status'] != 'known':
            raise ValueError('comparison common budget must be explicitly known')
        components.append(LossComponent(c['name'], Quantity(q['value'], q['unit'], QuantityStatus(q['status']), q['reason']),
                                        tuple(c['effects']), c['solver']))
    if [c.name for c in components] != list(NONLOCAL) or any(c.effects != (c.name,) for c in components):
        raise ValueError('nonlocal effect slots must be exactly free_space/gas/rain/clutter/other')
    compose_received_power(budget['eirp_dbm'], budget['receiver_gain_dbi'], tuple(components))
    return tuple(components)


def shared_profile(context, geometry, receiver):
    """Geometry preprocessing shared outside the independent reference kernel."""
    ground, _ = context.grid.sample(0, 0)
    agl = receiver['antenna_ellipsoid_height_m']-ground if ground is not None else 0
    profile = cell_profile(context.grid, receiver_east_m=0, receiver_north_m=0, antenna_agl_m=agl,
                           azimuth_deg=geometry['azimuth_deg'], radius_m=context.radius_m,
                           step_m=context.step_m, effective_radius_m=context.effective_radius_m)
    candidates = list(profile['samples']) + loss_extrema(profile, geometry['elevation_deg'],
                                                        geometry['slant_range_m'], geometry['frequency_hz'])
    el = math.radians(geometry['elevation_deg'])
    length = geometry['slant_range_m']
    reasons = list(profile['incomplete_reasons'])
    if length*math.cos(el) <= context.radius_m:
        reasons.append('satellite_within_profile_radius; shorten_profile')
    points, excluded = [], 0
    for sample in candidates:
        x, relative = sample['distance_m'], sample['relative_height_m']
        if relative is None or x >= length*math.cos(el):
            continue
        if x == 0 and relative <= 0:
            continue
        s, h = x*math.cos(el)+relative*math.sin(el), relative*math.cos(el)-x*math.sin(el)
        finite(s, 'projected distance')
        finite(h, 'normal height')
        if s <= 0 and h < 0:
            excluded += 1
        elif not 0 < s < length:
            reasons.append('obstacle_projection_outside_link')
        else:
            points.append([s, h])
    return dict(profile=profile, candidates=candidates, projected_points=points,
                excluded_behind_receiver=excluded, incomplete_reasons=sorted(set(reasons)))


def binding(record, *, refinement=False):
    terrain = deepcopy(record['terrain'])
    if refinement:
        for name in ('step_m', 'profile_sha256', 'candidate_sha256'):
            terrain.pop(name)
    ids = record['identity']
    return dict(geometry=record['geometry'], terrain=terrain, budget=record['budget'],
                metadata={k: ids[k] for k in ('schema_version', 'sample_id', 'candidate_id', 'timestamp_utc',
                                             'pass_id', 'satellite_id', 'scene_id', 'config_hash')})


def compare_models(context, geometry, receiver, budget, *, metadata, provenance, reference_limits=None):
    """Return exactly three paired records plus hash-addressable profile evidence.

    Malformed requests raise before solving; callers archive rejected requests.
    Failures of individual solvers are retained as failed role rows.
    """
    started = time.perf_counter()
    if context.sampling_method != 'cell_intervals' or context.horizon_tolerance_deg is not None:
        raise ValueError('comparison requires cell_intervals without an additional sampling guard')
    context.validate_receiver(receiver)
    for key in ('elevation_deg', 'slant_range_m', 'frequency_hz'):
        finite(geometry[key], key, positive=key != 'elevation_deg')
    el, az = geometry['elevation_deg'], geometry['azimuth_deg']
    if not -90 <= el <= 90 or type(geometry['geometrically_above_local_horizontal']) is not bool:
        raise ValueError('invalid elevation or geometric visibility')
    if geometry['geometrically_above_local_horizontal'] != (el > 0):
        raise ValueError('geometric visibility disagrees with elevation')
    if az is not None:
        finite(az, 'azimuth_deg')
        if not 0 <= az < 360:
            raise ValueError('azimuth must be in [0,360)')
    elif abs(el) != 90:
        raise ValueError('null azimuth only allowed at zenith/nadir')
    for key in ('lon_deg', 'lat_deg', 'antenna_ellipsoid_height_m'):
        finite(receiver[key], key)
    ground, _ = context.grid.sample(0, 0)
    agl = receiver['antenna_ellipsoid_height_m']-ground if ground is not None else None
    common = components_from(budget)
    if budget['frequency_hz'] != geometry['frequency_hz']:
        raise ValueError('frequency mismatch')
    expected_fspl = free_space_loss_db(geometry['slant_range_m'], geometry['frequency_hz'])
    if common[0].quantity.value != expected_fspl:
        raise ValueError('free-space loss mismatch')
    descriptor = context.descriptor()
    terrain = {k: descriptor[k] for k in ('source_id', 'grid_sha256', 'grid_geometry', 'vertical_datum',
                                         'surface_type', 'radius_m', 'step_m', 'sampling_method', 'effective_radius_m')}
    terrain.update(native_spacing_m=metadata['native_spacing_m'], profile_sha256=None, candidate_sha256=None,
                   loss_cap_db=context.loss_cap_db,
                   reference_limits=reference_limits or dict(maximum_points=8192, maximum_depth=256, maximum_nodes=16383))
    evidence = None
    preparation_error = None
    if 0 < el < 90 and az is not None:
        try:
            evidence = shared_profile(context, geometry, receiver)
            terrain.update(profile_sha256=identity(evidence['profile']), candidate_sha256=identity(evidence['projected_points']))
        except (ValueError, ArithmeticError) as exc:
            preparation_error = str(exc)
    ids = dict(schema_version=1, **{k: metadata[k] for k in ('sample_id', 'candidate_id', 'timestamp_utc', 'pass_id',
                                                          'satellite_id', 'scene_id', 'config_hash')})
    common_record = dict(identity=ids, geometry=dict(azimuth_deg=az, elevation_deg=el,
                         slant_range_m=geometry['slant_range_m'], geometrically_above_local_horizontal=el > 0,
                         receiver_lon_deg=receiver['lon_deg'], receiver_lat_deg=receiver['lat_deg'],
                         receiver_ellipsoid_height_m=receiver['antenna_ellipsoid_height_m'], height_above_surface_m=agl),
                         terrain=terrain, budget=deepcopy(budget))
    ids['query_id'] = identity(binding(common_record, refinement=True))
    ids['pair_id'] = ids['input_checksum'] = identity(binding(common_record))
    preparation_s = time.perf_counter()-started
    rows = []
    for role in ROLES:
        start = time.perf_counter()
        row = deepcopy(common_record)
        scope = terrain_scope(descriptor)
        result = dict(status='not_computed', failure_kind=None, reasons=[], visibility='unknown',
                      horizon_deg=None, limiting_distance_m=None, raw_loss_db=None, used_loss_db=None,
                      loss_cap_db=context.loss_cap_db, cap_triggered=False, margin_by_threshold={},
                      terrain_contract=scope, warnings=['not_physical_truth', 'finite_radius_only'])
        detail = {}
        try:
            if el <= 0:
                result.update(status='not_applicable', failure_kind='not_applicable',
                              visibility='not_applicable', reasons=['not_above_local_horizontal'])
            elif el == 90 or az is None:
                result.update(failure_kind='unsupported_geometry', reasons=['zenith_profile_not_supported'])
            elif preparation_error:
                result.update(status='failed', failure_kind='numerical_failure', reasons=[preparation_error])
            elif role == ROLES[0]:
                detail = cell_horizon(context.grid, receiver_east_m=0, receiver_north_m=0,
                                      antenna_agl_m=agl or 0, azimuth_deg=az, radius_m=context.radius_m,
                                      effective_radius_m=context.effective_radius_m)
                reasons = list(detail['incomplete_reasons'])
                if geometry['slant_range_m']*math.cos(math.radians(el)) <= context.radius_m:
                    reasons.append('satellite_within_profile_radius; shorten_profile')
                blocked = detail['horizon_deg'] is not None and el < detail['horizon_deg']
                result.update(status='known' if not reasons else 'not_computed', reasons=reasons,
                              visibility='blocked' if blocked else ('unknown' if reasons else 'clear_within_radius'),
                              horizon_deg=detail['horizon_deg'], limiting_distance_m=detail['limiting_distance_m'])
            elif role == ROLES[1]:
                detail = context.evaluate(geometry, receiver)
                result.update(status=detail['loss_status'], visibility=detail['los_status'],
                              reasons=detail.get('incomplete_reasons', []),
                              raw_loss_db=detail.get('raw_loss_db'), used_loss_db=detail.get('used_loss_db'),
                              cap_triggered=detail.get('cap_triggered', False),
                              horizon_deg=detail.get('profile', {}).get('horizon_deg'),
                              limiting_distance_m=detail.get('profile', {}).get('limiting_distance_m'))
            else:
                reasons = evidence['incomplete_reasons']
                if reasons:
                    result.update(reasons=reasons, visibility='blocked' if any(h > 1e-8 for _, h in evidence['projected_points']) else 'unknown')
                else:
                    detail = solve_edges(evidence['projected_points'], length_m=geometry['slant_range_m'],
                                         frequency_hz=geometry['frequency_hz'], loss_cap_db=context.loss_cap_db,
                                         **terrain['reference_limits'])
                    result.update(status='known', **{k: detail[k] for k in ('raw_loss_db', 'used_loss_db', 'cap_triggered', 'visibility')})
            if result['reasons'] and result['failure_kind'] is None:
                result['failure_kind'] = ('data_gap' if any(any(tag in r for tag in ('nodata', 'outside_dem', 'receiver_'))
                                                           for r in result['reasons']) else 'unsupported_geometry')
        except ResourceLimit as exc:
            result.update(status='failed', failure_kind='resource_limit', reasons=[str(exc)])
        except (ValueError, ArithmeticError) as exc:
            result.update(status='failed', failure_kind='numerical_failure', reasons=[str(exc)])
        reason = ';'.join(result['reasons']) or 'finite_radius_conditional'
        status = 'not_applicable' if role == ROLES[0] else result['status']
        local = Quantity(result['used_loss_db'], 'dB', QuantityStatus(status),
                         'sky_has_no_attenuation_model' if role == ROLES[0] else reason)
        result['local_loss'] = local.to_mapping()
        if status in ('not_applicable', 'not_computed', 'failed'):
            power = Quantity(None, 'dBm', QuantityStatus(status), local.reason)
        else:
            power = compose_received_power(budget['eirp_dbm'], budget['receiver_gain_dbi'],
                                           (*common, LossComponent('local', local, ('local',), role)))
        result['received_power'] = power.to_mapping()
        result['received_power']['terrain_contract'] = deepcopy(scope)
        base = compose_received_power(budget['eirp_dbm'], budget['receiver_gain_dbi'], common)
        result['margin_by_threshold'] = {str(offset): quantity(power.value-base.value-offset if power.value is not None else None,
                                                              'dB', power.status, power.reason)
                                         for offset in budget['threshold_offsets_db']}
        row['model'] = dict(role_id=role, version=1,
                            model_family=('horizon' if role == ROLES[0] else 'single_edge' if role == ROLES[1] else 'multi_edge'),
                            solver_source=('geometry/cell_horizon.py' if role == ROLES[0] else
                                           'engine/terrain_link.py' if role == ROLES[1] else 'engine/multi_edge.py'),
                            code_commit=provenance['code_commit'], source_fingerprint=provenance['source_fingerprint'],
                            included_effects=[] if role == ROLES[0] else [*NONLOCAL, 'local'],
                            excluded_effects=['multipath', 'fast_fading', 'service_scheduling'],
                            evidence_level='V0' if context.grid.surface_type == 'synthetic' else 'numerical_model_unverified',
                            reference_eligibility='unverified' if role == ROLES[2] and status == 'known' else 'unavailable' if role == ROLES[2] else 'not_reference',
                            independence_limits='shared source raster/profile/stationary candidates and ideal-edge assumptions; separate reference recursion; no measurements')
        row['identity']['result_id'] = identity(dict(pair_id=ids['pair_id'], model=row['model']))
        row['result'] = result
        row['solver_detail'] = detail
        row['resources'] = dict(wall_time_s=time.perf_counter()-start, shared_preparation_time_s=preparation_s,
                                point_count=detail.get('point_count', len(detail.get('samples', []))),
                                node_count=detail.get('node_count'), depth=detail.get('depth'),
                                process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                                memory_attribution='process_shared')
        rows.append(row)
    validate_pair(rows)
    return rows, evidence


def validate_pair(rows):
    """Reject missing/duplicate roles, mutated bindings, or incompatible budgets."""
    if len(rows) != 3 or {r['model']['role_id'] for r in rows} != set(ROLES):
        raise ValueError('pair requires exactly three unique roles')
    first = rows[0]
    for row in rows:
        required = {
            'identity': 'schema_version sample_id candidate_id timestamp_utc pass_id satellite_id scene_id query_id pair_id config_hash input_checksum result_id',
            'geometry': 'azimuth_deg elevation_deg slant_range_m geometrically_above_local_horizontal receiver_lon_deg receiver_lat_deg receiver_ellipsoid_height_m height_above_surface_m',
            'terrain': 'source_id grid_sha256 grid_geometry vertical_datum surface_type native_spacing_m radius_m step_m sampling_method effective_radius_m profile_sha256 candidate_sha256 loss_cap_db reference_limits',
            'budget': 'frequency_hz power_mode eirp_dbm transmit_power_dbm transmit_gain_dbi receiver_gain_dbi antenna_model_id pointing mean_power_definition nonlocal_components threshold_offsets_db',
            'model': 'role_id version model_family solver_source code_commit source_fingerprint included_effects excluded_effects evidence_level reference_eligibility independence_limits',
            'result': 'status failure_kind reasons visibility horizon_deg limiting_distance_m local_loss raw_loss_db used_loss_db loss_cap_db cap_triggered received_power margin_by_threshold terrain_contract warnings',
            'resources': 'wall_time_s point_count node_count depth process_peak_rss_kib memory_attribution',
        }
        for section, fields in required.items():
            if section not in row or not set(fields.split()).issubset(row[section]):
                raise ValueError(f'missing required {section} fields')
        if binding(row) != binding(first):
            raise ValueError('paired physical inputs differ')
        ids, model, result = row['identity'], row['model'], row['result']
        if ids['schema_version'] != 1:
            raise ValueError('unsupported schema')
        if ids['pair_id'] != identity(binding(row)) or ids['input_checksum'] != ids['pair_id']:
            raise ValueError('pair identity mismatch')
        if ids['query_id'] != identity(binding(row, refinement=True)):
            raise ValueError('query identity mismatch')
        if ids['result_id'] != identity(dict(pair_id=ids['pair_id'], model=model)):
            raise ValueError('result identity mismatch')
        if ids['timestamp_utc'] is not None:
            stamp = datetime.fromisoformat(ids['timestamp_utc'].replace('Z', '+00:00'))
            if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
                raise ValueError('timestamp must be UTC')
        if not all(isinstance(ids[k], str) and ids[k] for k in ('sample_id', 'candidate_id', 'scene_id', 'config_hash')):
            raise ValueError('identity metadata missing')
        if any(model[k] != first['model'][k] for k in ('source_fingerprint', 'code_commit')):
            raise ValueError('source identity mismatch')
        common = components_from(row['budget'])
        geometry, terrain, budget = (row[k] for k in ('geometry', 'terrain', 'budget'))
        for key in ('elevation_deg', 'slant_range_m', 'receiver_lon_deg', 'receiver_lat_deg', 'receiver_ellipsoid_height_m'):
            finite(geometry[key], key, positive=key == 'slant_range_m')
        elevation, azimuth = geometry['elevation_deg'], geometry['azimuth_deg']
        if not -90 <= elevation <= 90 or geometry['geometrically_above_local_horizontal'] is not (elevation > 0):
            raise ValueError('invalid geometry')
        if azimuth is None:
            if abs(elevation) != 90:
                raise ValueError('undefined azimuth away from zenith/nadir')
        else:
            finite(azimuth, 'azimuth')
            if not 0 <= azimuth < 360:
                raise ValueError('invalid azimuth')
        if not -180 <= geometry['receiver_lon_deg'] <= 180 or not -89.9 <= geometry['receiver_lat_deg'] <= 89.9:
            raise ValueError('receiver coordinates outside supported domain')
        if geometry['height_above_surface_m'] is not None:
            finite(geometry['height_above_surface_m'], 'height_above_surface_m')
            if geometry['height_above_surface_m'] < 0:
                raise ValueError('negative antenna height')
        finite(budget['frequency_hz'], 'frequency', positive=True)
        if common[0].quantity.value != free_space_loss_db(geometry['slant_range_m'], budget['frequency_hz']):
            raise ValueError('incorrect common free-space loss')
        for key in ('radius_m', 'step_m', 'native_spacing_m'):
            finite(terrain[key], key, positive=True)
        if terrain['vertical_datum'] != 'WGS84_ellipsoid' or terrain['sampling_method'] != 'cell_intervals':
            raise ValueError('unsupported terrain contract')
        if result['loss_cap_db'] != terrain['loss_cap_db']:
            raise ValueError('loss cap identity mismatch')
        if model['evidence_level'] == 'V2':
            raise ValueError('measurement evidence is not provided by this experiment')
        for name, unit in (('local_loss', 'dB'), ('received_power', 'dBm')):
            q = result[name]
            if q['unit'] != unit:
                raise ValueError('invalid quantity unit')
            Quantity(q['value'], unit, QuantityStatus(q['status']), q['reason'])
        sky = model['role_id'] == ROLES[0]
        expected_effects = [] if sky else [*NONLOCAL, 'local']
        if model['included_effects'] != expected_effects:
            raise ValueError('model contains missing or duplicate effects')
        if sky and (any(result[n]['status'] != 'not_applicable' for n in ('local_loss', 'received_power'))
                    or result['raw_loss_db'] is not None or result['used_loss_db'] is not None or result['cap_triggered']):
            raise ValueError('sky model cannot emit attenuation or power')
        if result['visibility'] not in ('clear_within_radius', 'blocked', 'unknown', 'not_applicable'):
            raise ValueError('invalid visibility')
        if result['terrain_contract'] != terrain_scope(row['terrain']):
            raise ValueError('finite-radius scope mismatch')
        if result['received_power']['terrain_contract'] != result['terrain_contract']:
            raise ValueError('power scope missing')
        if not sky and result['local_loss']['status'] == 'known':
            raw, used, cap = (result[k] for k in ('raw_loss_db', 'used_loss_db', 'loss_cap_db'))
            for key, value in (('raw', raw), ('used', used), ('cap', cap)):
                finite(value, key)
            if min(raw, used, cap) < 0 or used != min(raw, cap) or result['cap_triggered'] != (raw > cap):
                raise ValueError('inconsistent cap')
            if result['local_loss']['value'] != used or result['status'] != 'known':
                raise ValueError('local quantity inconsistent')
            q = Quantity(used, 'dB', QuantityStatus.KNOWN, 'finite_radius_conditional')
            expected = compose_received_power(row['budget']['eirp_dbm'], row['budget']['receiver_gain_dbi'],
                                               (*common, LossComponent('local', q, ('local',), model['role_id'])))
            if result['received_power']['value'] != expected.value or result['received_power']['status'] != 'known':
                raise ValueError('power inconsistent')
        elif not sky and any(result[k] is not None for k in ('raw_loss_db', 'used_loss_db')):
            raise ValueError('unavailable loss cannot have a value')
        elif not sky and result['received_power']['status'] == 'known':
            raise ValueError('unavailable local loss cannot yield known power')
        offsets = budget['threshold_offsets_db']
        if not offsets or len(set(offsets)) != len(offsets):
            raise ValueError('invalid thresholds')
        if set(result['margin_by_threshold']) != {str(o) for o in offsets}:
            raise ValueError('missing threshold margins')
        base = compose_received_power(budget['eirp_dbm'], budget['receiver_gain_dbi'], common).value
        for offset in offsets:
            finite(offset, 'threshold offset')
            margin, power = result['margin_by_threshold'][str(offset)], result['received_power']
            Quantity(margin['value'], margin['unit'], QuantityStatus(margin['status']), margin['reason'])
            if margin['unit'] != 'dB' or margin['status'] != power['status']:
                raise ValueError('margin status/units inconsistent')
            if power['status'] == 'known' and margin['value'] != power['value']-base-offset:
                raise ValueError('margin value inconsistent')
    return True
