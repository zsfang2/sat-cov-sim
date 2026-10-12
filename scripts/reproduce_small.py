"""Run the bundled, offline M0–M6 / E1–E4 reproduction subset."""

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from satellite_coverage.data_sources.manifest import checksum_sha256
from satellite_coverage.io.run_record import RunRecord, archive_sources, environment_record


def read(path):
    return json.loads(Path(path).read_text())


def verify_inputs(root):
    manifest = read(root/'reproduction/input-manifest.json')
    for name, expected in (manifest['files'] | manifest['configs']).items():
        path = root/name
        if not path.is_relative_to(root) or '..' in Path(name).parts or Path(name).is_absolute():
            raise ValueError('unsafe manifest path')
        if checksum_sha256(path) != expected:
            raise ValueError('input identity mismatch: '+name)
    return manifest


def compare(left, right, tolerance=1e-6, path='$'):
    """Numerical absolute tolerance; structure, identities and statuses stay exact."""
    if isinstance(left, dict) and isinstance(right, dict):
        if left.keys() != right.keys():
            raise ValueError('different fields at '+path)
        for key in left:
            compare(left[key], right[key], tolerance, path+'.'+key)
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            raise ValueError('different lengths at '+path)
        for i, (a, b) in enumerate(zip(left, right)):
            compare(a, b, tolerance, f'{path}[{i}]')
    elif type(left) in (int, float) and type(right) in (int, float):
        if not math.isfinite(left) or not math.isfinite(right) or abs(left-right) > tolerance:
            raise ValueError('numerical mismatch at '+path)
    elif type(left) is not type(right) or left != right:
        raise ValueError('discrete mismatch at '+path)


def semantic_results(output, manifest):
    """Explicit scientific projection; full cost/identity records stay in subruns."""
    e1 = read(output/'e1/factors.json')
    e2 = [json.loads(line) for line in (output/'e2/roles.jsonl').read_text().splitlines()]
    e4 = read(output/'e4/summary.json')
    result = dict(input_manifest=manifest,
        synthetic_events=read(output/'synthetic-events/summary.json'),
        synthetic_selection=read(output/'synthetic-selection/summary.json'),
        e1=[{k:r[k] for k in ('scene','case','parameters','spacing_deg','method','direct_budget','cached_budget','power_error_db','m1_crosscheck')} for r in e1],
        e1_errors=read(output/'e1/errors.json'),
        e2=[dict(scene=r['identity']['scene_id'],sample=r['identity']['sample_id'],geometry=r['geometry'],
                 terrain=r['terrain'],role=r['model']['role_id'],result=r['result']) for r in e2],
        e3_convergence=read(output/'e3/convergence.json'),
        e3_comparisons=read(output/'e3/comparisons.json'),
        e3_selection=read(output/'e3/selection.json'),
        e4={k:e4[k] for k in ('candidate_set_checksum','pass_registry_checksum','cases','reference_cases',
                             'reference_eligible','holdout_reference_cases','holdout_reference_eligible','judgment')})
    # Exact windows and time-integrals, separate from source/environment-bound IDs.
    for stage, pattern in [('e3','*-level*.json'),('e4','*-final.json')]:
        result[stage+'_events'] = {p.name:{k:read(p)[k] for k in ('observation','candidate_ids','candidates','opportunity')}
                                  for p in sorted((output/stage).glob(pattern))}
    return result


def run(output, expected=None):
    root = Path(__file__).resolve().parents[1]
    archive = RunRecord(Path(output).resolve())
    try:
        manifest = verify_inputs(root)
        archive.write('input-manifest.json', manifest)
        archive.write('environment.json', environment_record(root))
        archive_sources(root, archive.path/'sources.zip')
        tasks = [
            ('synthetic-events', 'verify_quality_events.py', []),
            ('synthetic-selection', 'verify_candidate_selection.py', []),
            ('e1', 'verify_direction_cache.py', ['--config','configs/reproduce_e1.yaml','--freeze','reproduction/inputs/e1-freeze.json']),
            ('e2', 'verify_model_comparison.py', ['--config','configs/reproduce_e2.yaml']),
            ('e3', 'verify_pass_events.py', ['--config','configs/reproduce_e3.yaml','--freeze','reproduction/inputs/e3-freeze.json']),
            ('e4', 'verify_information_value.py', ['--config','configs/reproduce_e4.yaml','--inputs','reproduction/inputs/e4']),
        ]
        env = dict(os.environ, MPLCONFIGDIR=str(archive.path/'matplotlib'), PYTHONNOUSERSITE='1')
        for stage, script, arguments in tasks:
            command = [sys.executable, str(root/'scripts'/script), *arguments, '--output', str(archive.path/stage)]
            archive.log('start '+stage)
            with (archive.path/(stage+'.log')).open('w') as log:
                subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
            if read(archive.path/stage/'validation.json')['status'] != 'passed':
                raise ValueError('stage did not pass: '+stage)
            print(stage+' passed', flush=True)
        with (archive.path/'e4-audit.log').open('w') as log:
            subprocess.run([sys.executable,str(root/'scripts/audit_information_value.py'),
                            '--run',str(archive.path/'e4'),'--output',str(archive.path/'e4-audit.json')],
                           cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        semantic = semantic_results(archive.path, manifest)
        archive.write('semantic.json', semantic)
        if expected is not None:
            compare(read(expected), semantic, manifest['comparison']['absolute_float_tolerance'])
            archive.write('comparison.json',dict(status='passed',expected_sha256=checksum_sha256(expected),
                tolerance=manifest['comparison'],scope='explicit scientific projections, not timing equality'))
        # Recursive manifest includes the independently recoverable subrun sources/data/results.
        hashes = {str(p.relative_to(archive.path)):checksum_sha256(p) for stage,_,_ in tasks
                  for p in (archive.path/stage).rglob('*') if p.is_file()}
        archive.write('subrun-artifacts.json',dict(files=hashes))
        archive.finish('passed',stages=[t[0] for t in tasks],compared=expected is not None,
                       scope='small retrospective reproducibility subset, not physical/service qualification')
    except Exception as exc:
        archive.finish('failed',error=str(exc))
        raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--expected',type=Path)
    args=parser.parse_args()
    run(args.output,args.expected)
