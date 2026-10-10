from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from satellite_coverage.engine.quality_events import classify, direct_events
from satellite_coverage.experiments.information_value import layer_record, unavailable_reference, uncertainty_intervals


def propagation():
    return dict(timestamp_utc='2025-01-01T00:00:00+00:00', satellite_id='sat', checksum='source',
        geometry=dict(elevation_deg=20), base_eirp_dbm=55,
        layers=dict(no_terrain=dict(status='computed',power_dbm=-130,reason='fixed'),
                    sky_proxy=dict(status='computed',visibility='clear_within_radius',reason='geometry'),
                    m3_single_edge=dict(status='computed',power_dbm=-150,reason='fixed'),
                    m4_multi_edge_reference=dict(status='unknown',power_dbm=None,reason='not_converged')))


def test_sky_clear_never_implies_quality_or_fake_db_and_blocked_is_geometric():
    source=propagation()
    clear=layer_record(source,'sky_proxy',55,-160)
    assert clear['budget'] is None and classify(clear)['quality']=='unknown'
    source['layers']['sky_proxy']['visibility']='blocked'
    blocked=layer_record(source,'sky_proxy',55,-160)
    assert classify(blocked)['geometry']=='visible'
    assert classify(blocked)['quality']=='invisible'
    blocked['budget']={'margin':dict(value=0,status='known',unit='dB')}
    with pytest.raises(ValueError,match='cannot contain'):
        classify(blocked)


def test_scenario_identity_and_unknown_reference_are_preserved():
    source=propagation(); original=deepcopy(source)
    a=layer_record(source,'m3_single_edge',55,-160)
    b=layer_record(source,'m3_single_edge',45,-160)
    c=layer_record(source,'m3_single_edge',55,-140)
    assert [classify(x)['quality'] for x in (a,b,c)]==['sufficient','sufficient','insufficient']
    assert a['budget']['margin']['value']-b['budget']['margin']['value']==10
    assert len({x['config_checksum'] for x in (a,b,c)})==3 and source==original
    assert classify(layer_record(source,'m4_multi_edge_reference',55,-160))['quality']=='unknown'


@pytest.mark.parametrize('geometry',[None,dict(elevation_deg=-1),dict(elevation_deg=20)])
def test_sky_budget_is_rejected_even_with_unavailable_or_invisible_geometry(geometry):
    record=layer_record(propagation(),'sky_proxy',55,-160)
    record.update(geometry=geometry,budget=dict(received_power=-10))
    with pytest.raises(ValueError,match='cannot contain'):
        classify(record)


def test_temporal_failure_keeps_full_observation_and_below_horizon():
    begin=datetime(2025,1,1,tzinfo=timezone.utc)
    def direct(t):
        source=propagation(); source['timestamp_utc']=t.isoformat()
        source['geometry']['elevation_deg']=20 if (t-begin).total_seconds()>2 else -1
        return layer_record(source,'no_terrain',55,-160)
    events=direct_events({'sat':direct},start=begin.isoformat(),end=(begin+timedelta(seconds=10)).isoformat(),
        step_s=2,max_probe_step_s=1,event_tolerance_s=.01,candidate_identities={'sat':'known'})
    unknown=unavailable_reference(events,'time_did_not_converge')
    assert unknown['observation']==events['observation']
    seconds=unknown['candidates']['sat']['quality']['seconds']
    assert seconds['sufficient']==0 and seconds['invisible']==2
    assert seconds['unknown']==8 and sum(seconds.values())==10


def test_uncertainty_intervals_do_not_turn_unknown_ranking_into_proven_gain():
    metrics=[dict(candidate_id='A',feasible=True,insufficient_s=1,invisible_s=1,unknown_s=8,objective_s=10),
             dict(candidate_id='B',feasible=True,insufficient_s=3,invisible_s=1,unknown_s=0,objective_s=4)]
    result=uncertainty_intervals(dict(selected=metrics[1],all_candidate_metrics=metrics))
    assert result['regret_lower_s']==0 and result['regret_upper_s']==2
    assert result['selected_upper_s']==result['selected_lower_s']==4


def test_actual_spatial_adapter_pairs_three_levels_and_reuses_exact_queries():
    import io
    import json
    import numpy as np
    from satellite_coverage.experiments.information_value import PropagationLedger
    from satellite_coverage.geometry.terrain import TerrainGrid
    from satellite_coverage.config.pilot import identity
    cfg=dict(radius_m=60,spatial_steps_m=[15,7.5,3.75],effective_radius_m=6371000,loss_cap_db=60,
        frequency_hz=14.5e9,eirps_dbm=[55,45],atmosphere_loss_db=1,resolution_m=30,
        norad_id='sat',maximum_points=8192,maximum_depth=256,maximum_nodes=16383,spatial_raw_tolerance_db=.1)
    grid=TerrainGrid(np.zeros((7,7)),-105,105,30,'WGS84_ellipsoid','flat',surface_type='synthetic')
    receiver=dict(lon_deg=108.9,lat_deg=33.9,antenna_ellipsoid_height_m=2)
    def base(t):
        return dict(status='computed',geometry=dict(elevation_deg=45,azimuth_deg=45,slant_range_m=600000,
            geometrically_above_local_horizontal=True),budget=dict(received_power=dict(value=-116,status='known')))
    stream=io.StringIO()
    ledger=PropagationLedger(base,grid,receiver,cfg,'A','p',dict(code_commit='test',source_fingerprint='test'),stream,native_spacing_m=30)
    t=datetime(2025,1,1,tzinfo=timezone.utc)
    result=ledger(t)
    assert result['reference_eligibility']['eligibility']=='eligible_within_tested_discretization'
    assert layer_record(result,'m4_multi_edge_reference',55,-160)['budget']['received_power']['status']=='known'
    assert ledger(t)==result and ledger.costs['direct_queries']==ledger.costs['analysis_reuses']==1
    archived=json.loads(stream.getvalue()); checksum=archived.pop('checksum')
    assert identity(archived)==checksum and len(archived['paired_evidence'])==9
