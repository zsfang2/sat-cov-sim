"""Machine-readable limits of a finite terrain calculation, not new physics."""

from ..config.pilot import identity


def terrain_scope(descriptor):
    return dict(version=1, scope='finite_radius_conditional',
                radius_m=descriptor['radius_m'], step_m=descriptor['step_m'],
                sampling_method=descriptor['sampling_method'], full_path_status='not_verified',
                business_threshold_status='undetermined', service_eligibility='unknown',
                limitations=['terrain_outside_radius_unverified', 'declared_local_diffraction_model',
                             'DSM_surface_is_not_bare_ground'])


def failure_kind(record):
    terrain = record.get('terrain', {})
    geometry = record.get('geometry')
    if record['status'] == 'failed':
        return 'solver_failure'
    if geometry is None:
        return 'upstream_unavailable'
    if not geometry['geometrically_above_local_horizontal']:
        return 'not_applicable'
    reasons = terrain.get('incomplete_reasons', [])
    if any('nodata' in r or 'outside_dem' in r or 'receiver_missing' in r for r in reasons):
        return 'data_gap'
    if ('horizon_sampling_tolerance_not_met' in reasons
            or 'step_exceeds_native_resolution' in reasons):
        return 'sampling_not_verified'
    if terrain.get('loss_status') != 'known':
        return 'unsupported_geometry'
    power = record.get('budget', {}).get('received_power', {})
    if power.get('status') != 'known':
        return 'component_unavailable'
    return None


def attach_terrain_contract(record, descriptor, physical_id, frequency_hz, receiver):
    geometry = record.get('geometry') or {}
    terrain = record.get('terrain', {})
    budget = record.get('budget')
    power = budget['received_power'] if budget else None
    binding = {name: record[name] for name in ('sample_id','timestamp_utc','candidate_id')}
    binding.update({name: geometry.get(name) for name in ('azimuth_deg','elevation_deg','slant_range_m')})
    binding.update(frequency_hz=frequency_hz, receiver_ellipsoid_height_m=receiver['antenna_ellipsoid_height_m'],
                   terrain_radius_m=descriptor['radius_m'], terrain_step_m=descriptor['step_m'],
                   terrain_grid_sha256=descriptor['grid_sha256'], terrain_source_id=descriptor['source_id'],
                   physical_input_checksum=physical_id)
    binding['query_id'] = identity(binding)
    contract = terrain_scope(descriptor)
    contract.update(finite_loss_status=terrain.get('loss_status','not_computed'),
                    finite_power_status=power['status'] if power else 'not_computed',
                    failure_kind=failure_kind(record), radius_audit_status='not_attached',
                    audit_binding=binding)
    record['terrain_contract'] = contract
    if power is not None:
        # A consumer extracting just the power still receives its applicability.
        power['terrain_contract'] = terrain_scope(descriptor)
    return contract
