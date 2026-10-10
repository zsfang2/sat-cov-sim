"""Freeze a geometric split and separately centered terrain inputs before E4 quality."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil

import numpy as np
from pyproj import Transformer
import yaml

from satellite_coverage.config.pilot import identity
from satellite_coverage.data_sources.manifest import checksum_sha256
from satellite_coverage.data_sources.terrain_dem import load_terrain_dem
from satellite_coverage.engine.candidate_selection import CandidateSet, PassRegistry
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record
from satellite_coverage.orbit.visibility import parse_catalog, point_windows, select_record, utc


def prepare(config_path, output):
    root = Path(__file__).resolve().parents[1]
    config_path = Path(config_path)
    cfg = yaml.safe_load(config_path.read_text())
    run = RunRecord(output)
    try:
        run.write('config.json', cfg)
        run.write('environment.json', environment_record(root))
        archive_sources(root, run.path/'sources.zip')
        transform = Transformer.from_crs(
            f"+proj=aeqd +lat_0={cfg['origin_lat_deg']} +lon_0={cfg['origin_lon_deg']} +datum=WGS84 +units=m",
            'EPSG:4326', always_xy=True)
        candidates = CandidateSet.from_mapping(dict(coordinate_basis='WGS84 AEQD at declared origin; metre ENU offsets',
            items=[dict(candidate_id=c['id'], east_m=c['east_m'], north_m=c['north_m'],
                        height_agl_m=cfg['height_agl_m'], cost=1, feasible=True,
                        reason='hypothetical equal installation cost; no land-use constraint') for c in cfg['sites']]))
        run.write('candidates.json', candidates.to_mapping())
        tle = root/cfg['tle_path']
        if checksum_sha256(tle) != cfg['tle_sha256']:
            raise ValueError('TLE checksum mismatch')
        shutil.copyfile(tle, run.path/'input.tle')
        catalog = parse_catalog(tle.read_bytes())
        sat = select_record(catalog.records[cfg['norad_id']], utc(cfg['search_start']), cfg['tle_policy'])
        if sat is None or max(abs((utc(cfg[k])-sat.epoch.utc_datetime()).total_seconds()) for k in ('search_start','search_end'))/86400 > cfg['max_age_days']:
            raise ValueError('frozen search lacks eligible past TLE')
        sites, windows = [], {}
        for site in cfg['sites']:
            lon, lat = transform.transform(site['east_m'], site['north_m'])
            stats = {}
            geoid = dict(cfg['geoid'], path=str(root/cfg['geoid']['path']))
            grid, meta = load_terrain_dem(root/cfg['dem_path'], cfg['dem_declaration'], lon_deg=lon, lat_deg=lat,
                radius_m=cfg['radius_m'], resolution_m=cfg['resolution_m'], geoid=geoid, diagnostics=stats)
            ground, reason = grid.sample(0, 0)
            if ground is None:
                raise ValueError(f"candidate {site['id']} ground unavailable: {reason}")
            receiver = dict(lon_deg=lon, lat_deg=lat, height_basis='ellipsoid',
                            antenna_ellipsoid_height_m=ground+cfg['height_agl_m'],
                            basis='declared Copernicus DSM + EGM2008 undulation + fixed above-surface height')
            filename = site['id']+'-grid.npy'
            np.save(run.path/filename, grid.elevations_m)
            run.write(site['id']+'-terrain.json', meta)
            run.write(site['id']+'-read.json', stats)
            sites.append(dict(candidate_id=site['id'], receiver=receiver, grid=filename,
                grid_sha256=checksum_sha256(run.path/filename), metadata=site['id']+'-terrain.json',
                metadata_sha256=checksum_sha256(run.path/(site['id']+'-terrain.json'))))
            windows[site['id']] = [w for w in point_windows(sat,dict(lon=lon,lat=lat,height_m=receiver['antenna_ellipsoid_height_m']),
                utc(cfg['search_start']),utc(cfg['search_end']),0) if not w['start_clipped'] and not w['end_clipped']]
            print('prepared',site['id'],'geometric complete passes',len(windows[site['id']]),flush=True)
        origin = windows[cfg['sites'][0]['id']]
        chosen = origin[cfg['skip_complete_passes']:cfg['skip_complete_passes']+cfg['complete_pass_count']]
        if len(chosen) != cfg['complete_pass_count']:
            raise ValueError('not enough complete chronological passes')
        passes, details = [], []
        for index, window in enumerate(chosen):
            matches = {}
            for site, observed in windows.items():
                matching = [w for w in observed if min(w['end'],window['end']) > max(w['start'],window['start'])]
                if len(matching) != 1:
                    raise ValueError('candidate complete-pass matching is ambiguous or missing')
                matches[site] = matching[0]
            begin = min(w['start'] for w in matches.values())-cfg['padding_s']
            end = max(w['end'] for w in matches.values())+cfg['padding_s']
            p = dict(pass_id=f"pass-{cfg['skip_complete_passes']+index+1}",
                split='development' if index < cfg['development_pass_count'] else 'holdout',
                start_utc=datetime.fromtimestamp(begin,timezone.utc).isoformat(),
                end_utc=datetime.fromtimestamp(end,timezone.utc).isoformat(),
                basis='chronological geometric overlap; union across candidates plus padding; no quality inspected')
            passes.append(p)
            details.append(dict(**p, geometric_windows=matches))
        registry = PassRegistry.from_mapping(dict(passes=passes))
        run.write('registry.json', registry.to_mapping())
        run.write('geometric-search.json', dict(all_complete_windows=windows, selected=details))
        run.write('freeze.json', dict(config_sha256=checksum_sha256(config_path), config_checksum=identity(cfg),
            candidate_set_checksum=candidates.checksum, pass_registry_checksum=registry.checksum,
            selected_tle_record_sha256=sat.record_sha256, tle_sha256=cfg['tle_sha256'], sites=sites,
            quality_evaluated=False, selection_basis='geometry and declared locations only'))
        run.finish('passed', scope='pre-quality inputs and whole-pass split frozen')
    except Exception as exc:
        run.finish('failed', error=str(exc))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/m6_e4.yaml')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    prepare(args.config, args.output)
