"""Archive every query's all-larger-radius audit from a completed sweep."""

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

from satellite_coverage.config.pilot import identity
from satellite_coverage.data_sources.manifest import checksum_sha256
from satellite_coverage.experiments.terrain_sensitivity import assess_query_radius_stability
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run = RunRecord(args.output)
    try:
        manifests = json.loads((args.input/'artifacts.json').read_text())['files']
        for name, digest in manifests.items():
            if Path(name).name != name or checksum_sha256(args.input/name) != digest:
                raise ValueError('invalid sweep artifact or checksum: '+name)
        if json.loads((args.input/'validation.json').read_text())['status'] != 'passed':
            raise ValueError('sweep incomplete; cannot infer missing query results')
        settings = json.loads((args.input/'config.json').read_text())
        if len(settings['steps_m']) != 1:
            raise ValueError('query radius audit requires one fixed step')
        archive_sources(root,run.path/'sources.zip')
        run.write('environment.json',environment_record(root))
        run.write('input.json',dict(path=str(args.input.resolve()),
                                   artifacts_sha256=checksum_sha256(args.input/'artifacts.json'),
                                   config=settings))
        summaries = []
        for site in settings['sites']:
            site_id = site['id']
            rows = json.loads((args.input/(site_id+'-samples.json')).read_text())
            expected = (len(settings['radii_m'])*len(settings['heights_above_surface_m'])*
                        len(settings['azimuths_deg']))
            if len(rows) != expected:
                raise ValueError('incomplete profile matrix')
            queries = assess_query_radius_stability(rows,
                horizon_tolerance_deg=settings['horizon_tolerance_deg'],
                loss_tolerance_db=settings['raw_loss_tolerance_db'])
            binding = identity(dict(config=settings,site=site,
                                    terrain_hash=manifests[site_id+'-terrain.json'],
                                    grid_hash=manifests[site_id+'-ellipsoid.npy']))
            per_radius = {str(radius): Counter() for radius in settings['radii_m']}
            counts = Counter()
            out = run.path/(site_id+'-queries.jsonl.gz')
            with out.open('wb') as raw, gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as stream:
                for query in queries:
                    record = dict(binding_id=binding,site=site,frequency_hz=settings['frequency_hz'],
                                  slant_range_m=settings['slant_range_m'],**query)
                    stream.write((json.dumps(record,allow_nan=False,sort_keys=True)+'\n').encode())
                    for entry in query['entries']:
                        counts[entry['status']] += 1
                        per_radius[str(entry['radius_m'])][entry['status']] += 1
            summaries.append(dict(site=site,binding_id=binding,queries=len(queries),
                                  query_radius_records=sum(counts.values()),status_counts=dict(counts),
                                  by_radius={k:dict(v) for k,v in per_radius.items()},
                                  all_query_archive=out.name,sha256=checksum_sha256(out)))
        run.write('summary.json',dict(sites=summaries,global_radius_sufficiency='not_verified',
                                     source_run_status='passed',
                                     resource_refused_queries=0,
                                     scope='All archived query outcomes retained; no global or interpolated-direction guarantee'))
        run.finish('passed',meaning='per-query evidence generated, not M3 acceptance')
    except Exception as exc:
        run.finish('failed',reason=str(exc))
        raise


if __name__ == '__main__':
    main()
