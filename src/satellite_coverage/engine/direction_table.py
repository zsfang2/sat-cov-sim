"""Identity-bound, finite-domain local propagation tables and safe queries."""

from bisect import bisect_left
from copy import deepcopy
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform

import numpy as np

from ..config.pilot import identity
from ..domain.link_record import Quantity, QuantityStatus
from .terrain_contract import terrain_scope


class CacheMismatch(ValueError):
    """Cached samples do not describe the requested physical solver inputs."""


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite')


def _positive_integer(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(f'{name} must be a positive integer')


def _direction(azimuth, elevation):
    _finite(elevation, 'elevation')
    if not -90 <= elevation <= 90:
        raise ValueError('elevation must be in [-90,90]')
    if azimuth is None:
        if abs(elevation) != 90:
            raise ValueError('null azimuth requires zenith/nadir')
        return None, float(elevation)
    _finite(azimuth, 'azimuth')
    return (None if abs(elevation) == 90 else float(azimuth % 360)), float(elevation)


def _validate_descriptor(descriptor):
    if not isinstance(descriptor, dict) or not {'environment', 'receiver', 'frequency_hz', 'model', 'system'}.issubset(descriptor):
        raise ValueError('local solver must declare environment/receiver/frequency/model/system')
    _finite(descriptor['frequency_hz'], 'frequency')
    if descriptor['frequency_hz'] <= 0 or any(not descriptor[k] for k in ('environment', 'receiver', 'model', 'system')):
        raise ValueError('incomplete solver identity')
    environment = descriptor['environment']
    if not {'radius_m', 'step_m', 'sampling_method', 'loss_cap_db'}.issubset(environment):
        raise ValueError('environment must declare finite terrain scope and cap')
    json.dumps(descriptor, allow_nan=False)


def _validate_response(response):
    needed = {'local_loss', 'raw_loss_db', 'loss_cap_db', 'cap_triggered', 'visibility', 'terrain_contract', 'included_effects', 'reasons'}
    if not isinstance(response, dict) or not needed.issubset(response):
        raise ValueError('invalid local response schema')
    q = response['local_loss']
    Quantity(q['value'], q['unit'], QuantityStatus(q['status']), q['reason'])
    if q['unit'] != 'dB' or response['included_effects'] != ['local']:
        raise ValueError('table accepts only local loss in dB; no FSPL or antenna gains')
    if response['visibility'] not in ('blocked', 'clear_within_radius', 'unknown', 'not_applicable'):
        raise ValueError('invalid visibility')
    if type(response['cap_triggered']) is not bool:
        raise ValueError('cap state must be boolean')
    _finite(response['loss_cap_db'], 'loss cap')
    if response['loss_cap_db'] < 0:
        raise ValueError('negative loss cap')
    if q['status'] == 'known':
        raw = response['raw_loss_db']
        _finite(raw, 'raw loss')
        if raw < 0 or q['value'] != min(raw, response['loss_cap_db']) or response['cap_triggered'] != (raw > response['loss_cap_db']):
            raise ValueError('inconsistent raw/used/cap')
    elif response['raw_loss_db'] is not None or response['cap_triggered']:
        raise ValueError('unavailable loss cannot carry raw value or cap flag')
    scope = response['terrain_contract']
    if scope != terrain_scope(scope):
        raise ValueError('finite-radius contract mismatch')
    json.dumps(response, allow_nan=False)


class TerrainLocalSolver:
    """Bind the existing local single-edge solver to one physical receiver.

    Finite-distance diffraction depends on slant range, so it is part of the
    identity. Power, antenna gain, FSPL and nonlocal components stay outside
    this local response and are recomposed by the caller.
    """

    def __init__(self, context, receiver, *, frequency_hz, slant_range_m):
        for name, value in (('frequency', frequency_hz), ('range', slant_range_m)):
            _finite(value, name)
            if value <= 0:
                raise ValueError('frequency and range must be positive')
        for name in ('lon_deg', 'lat_deg', 'antenna_ellipsoid_height_m'):
            _finite(receiver[name], name)
        context.validate_receiver(receiver)
        self._context = context
        self._receiver = deepcopy(receiver)
        self._frequency = frequency_hz
        self._range = slant_range_m
        root = Path(__file__).resolve().parents[1]
        files = sorted(p for folder in ('engine', 'geometry', 'domain') for p in (root/folder).glob('*.py'))
        sources = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        self._descriptor = dict(environment=context.descriptor(), receiver=deepcopy(receiver), frequency_hz=frequency_hz,
                                model=dict(name='local-dominant-knife-edge-v1', source_fingerprint=identity(sources),
                                           python=platform.python_version(), numpy=np.__version__),
                                system=dict(slant_range_m=slant_range_m, included_effects=['local'],
                                            averaging='scalar_mean_no_fast_fading', reference_power='additional_loss_only',
                                            excluded_effects=['free_space', 'gas', 'rain', 'clutter', 'antenna_gain']))

    def descriptor(self):
        return deepcopy(self._descriptor)

    def evaluate(self, azimuth_deg, elevation_deg):
        azimuth, elevation = _direction(azimuth_deg, elevation_deg)
        geometry = dict(azimuth_deg=azimuth, elevation_deg=elevation, slant_range_m=self._range,
                        frequency_hz=self._frequency, geometrically_above_local_horizontal=elevation > 0)
        result = self._context.evaluate(geometry, self._receiver)
        status = 'not_applicable' if elevation <= 0 else result['loss_status']
        reasons = result.get('incomplete_reasons', [result['reason']] if 'reason' in result else [])
        return dict(local_loss=Quantity(result['used_loss_db'], 'dB', QuantityStatus(status),
                                        ';'.join(reasons) or 'finite_radius_conditional').to_mapping(),
                    raw_loss_db=result.get('raw_loss_db'), loss_cap_db=self._context.loss_cap_db,
                    cap_triggered=result.get('cap_triggered', False), visibility=result['los_status'],
                    horizon_deg=result.get('profile', {}).get('horizon_deg'),
                    terrain_contract=terrain_scope(self._descriptor['environment']), included_effects=['local'], reasons=reasons)


class DirectionTable:
    """Regular full-period azimuth grid, bounded elevation grid, JSON cache.

    The provider protocol is descriptor() and evaluate(azimuth,elevation).
    Descriptors must include every physical/model/system dependency. The
    bundled TerrainLocalSolver constructs that descriptor from actual inputs.
    """

    def __init__(self, descriptor, azimuths, elevations, samples, *, zenith_guard_deg=89.9):
        _validate_descriptor(descriptor)
        self._descriptor = deepcopy(descriptor)
        self._azimuths = tuple(azimuths)
        self._elevations = tuple(elevations)
        self._guard = zenith_guard_deg
        self._validate_axes()
        if len(samples) != len(self._azimuths)*len(self._elevations):
            raise ValueError('sample grid size mismatch')
        self._samples = deepcopy(samples)
        for row, (azimuth, elevation) in zip(self._samples, itertools.product(self._azimuths, self._elevations)):
            if row['azimuth_deg'] != azimuth or row['elevation_deg'] != elevation:
                raise ValueError('sample order/coordinate mismatch')
            _validate_response(row['response'])
            if (row['response']['terrain_contract'] != terrain_scope(descriptor['environment'])
                    or row['response']['loss_cap_db'] != descriptor['environment']['loss_cap_db']):
                raise CacheMismatch('sample scope/cap differs from solver descriptor')
        for ai in range(len(self._azimuths)):
            for ei in range(len(self._elevations)):
                row = self._at(ai, ei)
                neighbors = [self._at((ai-1) % len(self._azimuths), ei), self._at((ai+1) % len(self._azimuths), ei)]
                neighbors += [self._at(ai, e) for e in (ei-1, ei+1) if 0 <= e < len(self._elevations)]
                def state(item):
                    response = item['response']
                    return response['local_loss']['status'], response['visibility'], response['cap_triggered']
                row['boundary'] = (row['response']['local_loss']['status'] != 'known'
                                   or any(state(n) != state(row) for n in neighbors))
        self._key = identity(self._identity())

    def _validate_axes(self):
        for axis in (self._azimuths, self._elevations):
            if len(axis) < 2:
                raise ValueError('both regular axes need at least two points')
            for value in axis:
                _finite(value, 'axis coordinate')
            delta = axis[1]-axis[0]
            if delta <= 0 or any(abs(b-a-delta) > 1e-10 for a, b in zip(axis, axis[1:])):
                raise ValueError('axes must be increasing and regularly spaced')
        if self._azimuths[0] != 0 or abs(self._azimuths[-1]+self._azimuths[1]-360) > 1e-10:
            raise ValueError('azimuth grid must tile [0,360) exactly')
        _finite(self._guard, 'zenith guard')
        if not 0 < self._guard < 90 or not 0 <= self._elevations[0] < self._elevations[-1] < self._guard:
            raise ValueError('elevation grid must be below the explicit zenith guard')

    def _identity(self):
        return dict(schema_version=1, solver=self._descriptor, azimuths_deg=list(self._azimuths),
                    elevations_deg=list(self._elevations), zenith_guard_deg=self._guard, storage='float64_json')

    @property
    def cache_key(self):
        return self._key

    @property
    def descriptor(self):
        return deepcopy(self._descriptor)

    @property
    def samples(self):
        return deepcopy(self._samples)

    @classmethod
    def build(cls, solver, *, azimuth_step_deg, elevations_deg, zenith_guard_deg=89.9,
              maximum_samples=100000, chunk_size=256):
        _positive_integer(maximum_samples, 'maximum samples')
        _positive_integer(chunk_size, 'chunk size')
        _finite(azimuth_step_deg, 'azimuth step')
        if azimuth_step_deg <= 0 or 360/azimuth_step_deg > maximum_samples:
            raise ValueError('invalid azimuth step or sample budget exceeded')
        count = round(360/azimuth_step_deg)
        if count < 2 or abs(count*azimuth_step_deg-360) > 1e-10:
            raise ValueError('azimuth step must divide 360 with at least two samples')
        elevations = list(elevations_deg)
        if count*len(elevations) > maximum_samples:
            raise ValueError('table sample budget exceeded')
        azimuths = [i*azimuth_step_deg for i in range(count)]
        descriptor = solver.descriptor()
        _validate_descriptor(descriptor)
        # Check the axis contract before invoking any potentially costly solver.
        shell = object.__new__(cls)
        shell._azimuths, shell._elevations, shell._guard = tuple(azimuths), tuple(elevations), zenith_guard_deg
        shell._validate_axes()
        directions = iter(itertools.product(azimuths, elevations))
        samples = []
        while chunk := list(itertools.islice(directions, chunk_size)):
            for azimuth, elevation in chunk:
                response = cls._solve(solver, azimuth, elevation, descriptor)
                samples.append(dict(azimuth_deg=azimuth, elevation_deg=elevation, response=response))
        if solver.descriptor() != descriptor:
            raise CacheMismatch('solver descriptor changed during table build')
        return cls(descriptor, azimuths, elevations, samples, zenith_guard_deg=zenith_guard_deg)

    @staticmethod
    def _solve(solver, azimuth, elevation, descriptor):
        try:
            response = solver.evaluate(azimuth, elevation)
            _validate_response(response)
            if (response['terrain_contract'] != terrain_scope(descriptor['environment'])
                    or response['loss_cap_db'] != descriptor['environment']['loss_cap_db']):
                raise CacheMismatch('solver response scope/cap differs from descriptor')
            return response
        except (ValueError, ArithmeticError, RuntimeError) as exc:
            environment = descriptor['environment']
            return dict(local_loss=Quantity(None, 'dB', QuantityStatus.FAILED, str(exc) or type(exc).__name__).to_mapping(),
                        raw_loss_db=None, loss_cap_db=environment['loss_cap_db'], cap_triggered=False,
                        visibility='unknown', terrain_contract=terrain_scope(environment), included_effects=['local'],
                        reasons=[str(exc) or type(exc).__name__])

    def _at(self, az_index, el_index):
        return self._samples[az_index*len(self._elevations)+el_index]

    def _fallback(self, azimuth, elevation, reason, solver, neighbors):
        if solver is not None:
            response = self._solve(solver, azimuth, elevation, self._descriptor)
            path = 'direct_fallback'
        else:
            environment = self._descriptor['environment']
            response = dict(local_loss=Quantity(None, 'dB', QuantityStatus.NOT_COMPUTED, reason).to_mapping(),
                            raw_loss_db=None, loss_cap_db=environment['loss_cap_db'], cap_triggered=False,
                            visibility='unknown', terrain_contract=terrain_scope(environment), included_effects=['local'], reasons=[reason])
            path = 'fallback_required'
        return self._output(azimuth, elevation, response, path, neighbors, reason)

    def _output(self, azimuth, elevation, response, path, neighbors, reason=None):
        return dict(azimuth_deg=azimuth, elevation_deg=elevation, cache_key=self._key,
                    solver_identity=identity(self._descriptor), response=deepcopy(response), method=path,
                    neighbors=neighbors, fallback_reason=reason,
                    domain=dict(azimuth_period_deg=360, elevation_min_deg=self._elevations[0],
                                elevation_max_deg=self._elevations[-1], zenith_guard_deg=self._guard),
                    error_bound_db=0.0 if path == 'sample' else None,
                    accuracy='stored_sample_reproduction' if path == 'sample' else 'direct_model_evaluation' if path == 'direct_fallback' else 'not_verified')

    def query(self, azimuth_deg, elevation_deg, *, method='bilinear', expected_descriptor,
              fallback_solver=None, error_tolerance_db=None):
        if expected_descriptor != self._descriptor:
            raise CacheMismatch('requested physical/model/system inputs differ from cache')
        if fallback_solver is not None and fallback_solver.descriptor() != self._descriptor:
            raise CacheMismatch('fallback solver differs from cache identity')
        if method not in ('nearest', 'bilinear'):
            raise ValueError('method must be nearest or bilinear')
        if error_tolerance_db is not None:
            _finite(error_tolerance_db, 'error tolerance')
            if error_tolerance_db < 0:
                raise ValueError('error tolerance must be nonnegative')
        azimuth, elevation = _direction(azimuth_deg, elevation_deg)
        if abs(elevation) >= self._guard:
            return self._fallback(azimuth, elevation, 'zenith_azimuth_degeneracy', fallback_solver, [])
        if not self._elevations[0] <= elevation <= self._elevations[-1]:
            return self._fallback(azimuth, elevation, 'outside_elevation_domain', fallback_solver, [])
        ai, ei = bisect_left(self._azimuths, azimuth), bisect_left(self._elevations, elevation)
        az_exact = ai < len(self._azimuths) and self._azimuths[ai] == azimuth
        el_exact = ei < len(self._elevations) and self._elevations[ei] == elevation
        if az_exact and el_exact:
            return self._output(azimuth, elevation, self._at(ai, ei)['response'], 'sample',
                                [dict(azimuth_index=ai, elevation_index=ei, weight=1.0)])
        if az_exact:
            az_weights = [(ai, 1.0)]
        else:
            left, right = ai-1, ai % len(self._azimuths)
            low = self._azimuths[left]
            high = self._azimuths[right] if right else 360
            fraction = (azimuth-low)/(high-low)
            az_weights = [(left, 1-fraction), (right, fraction)]
        if el_exact:
            el_weights = [(ei, 1.0)]
        else:
            fraction = (elevation-self._elevations[ei-1])/(self._elevations[ei]-self._elevations[ei-1])
            el_weights = [(ei-1, 1-fraction), (ei, fraction)]
        neighbors = [dict(azimuth_index=a, elevation_index=e, weight=aw*ew)
                     for a, aw in az_weights for e, ew in el_weights]
        responses = [self._at(n['azimuth_index'], n['elevation_index'])['response'] for n in neighbors]
        compatible = all(r['local_loss']['status'] == 'known' for r in responses)
        for key in ('visibility', 'loss_cap_db', 'cap_triggered', 'terrain_contract', 'included_effects'):
            compatible = compatible and all(r[key] == responses[0][key] for r in responses)
        if not compatible:
            return self._fallback(azimuth, elevation, 'incompatible_or_unavailable_stencil', fallback_solver, neighbors)
        if error_tolerance_db is not None:
            return self._fallback(azimuth, elevation, 'interpolation_error_not_certified', fallback_solver, neighbors)
        if method == 'nearest':
            # Highest bilinear weight is the nearest grid corner in normalized
            # cell coordinates; ties preserve canonical index order.
            index = max(range(len(neighbors)), key=lambda i: (neighbors[i]['weight'],
                                                            -neighbors[i]['azimuth_index'], -neighbors[i]['elevation_index']))
            response = responses[index]
            for i, n in enumerate(neighbors):
                n['weight'] = 1.0 if i == index else 0.0
        else:
            raw = math.fsum(r['raw_loss_db']*n['weight'] for r, n in zip(responses, neighbors))
            response = deepcopy(responses[0])
            response['raw_loss_db'] = raw
            response['local_loss'] = Quantity(min(raw, response['loss_cap_db']), 'dB', QuantityStatus.KNOWN,
                                               'bilinear_local_loss_approximation').to_mapping()
            response['cap_triggered'] = raw > response['loss_cap_db']
            response.pop('horizon_deg', None)
            response['reasons'] = []
        return self._output(azimuth, elevation, response, method, neighbors)

    def query_batch(self, directions, *, chunk_size=256, **kwargs):
        """Stream bounded query chunks; retain input order and every result."""
        _positive_integer(chunk_size, 'chunk size')
        iterator = iter(directions)
        while chunk := list(itertools.islice(iterator, chunk_size)):
            yield [self.query(az, el, **kwargs) for az, el in chunk]

    def save(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        payload = dict(**self._identity(), samples=self.samples)
        envelope = dict(cache_key=self._key, content_sha256=identity(payload), payload=payload)
        path = directory/(self._key.removeprefix('sha256:')+'.json')
        with path.open('x', encoding='utf-8') as stream:
            json.dump(envelope, stream, allow_nan=False, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
        return path

    @classmethod
    def load(cls, path, *, expected_descriptor, maximum_bytes=128*1024*1024, maximum_samples=100000):
        _positive_integer(maximum_bytes, 'maximum bytes')
        _positive_integer(maximum_samples, 'maximum samples')
        path = Path(path)
        if path.stat().st_size > maximum_bytes:
            raise ValueError('cache file exceeds read budget')
        with path.open('rb') as stream:
            data = stream.read(maximum_bytes+1)
        if len(data) > maximum_bytes:
            raise ValueError('cache file exceeds read budget')
        envelope = json.loads(data)
        payload = envelope['payload']
        if identity(payload) != envelope['content_sha256']:
            raise CacheMismatch('cache content checksum mismatch')
        if payload['solver'] != expected_descriptor:
            raise CacheMismatch('cache solver identity mismatch')
        if payload['schema_version'] != 1 or payload['storage'] != 'float64_json':
            raise ValueError('unsupported cache format')
        if len(payload['samples']) > maximum_samples:
            raise ValueError('cache sample budget exceeded')
        table = cls(payload['solver'], payload['azimuths_deg'], payload['elevations_deg'], payload['samples'],
                    zenith_guard_deg=payload['zenith_guard_deg'])
        if table.cache_key != envelope['cache_key']:
            raise CacheMismatch('cache key mismatch')
        return table
