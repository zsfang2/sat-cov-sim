"""Fail-closed reproduction identities and scientific comparison."""

import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

from satellite_coverage.io.run_record import archive_sources

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('reproduce_small',ROOT/'scripts/reproduce_small.py')
reproduce=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reproduce)


def test_input_identity_and_tamper(tmp_path):
    import shutil
    shutil.copytree(ROOT/'reproduction',tmp_path/'reproduction')
    shutil.copytree(ROOT/'configs',tmp_path/'configs')
    reproduce.verify_inputs(tmp_path)
    name=next(iter(json.loads((tmp_path/'reproduction/input-manifest.json').read_text())['files']))
    with (tmp_path/name).open('ab') as stream:stream.write(b'tampered')
    with pytest.raises(ValueError,match='identity mismatch'):
        reproduce.verify_inputs(tmp_path)


@pytest.mark.parametrize('left,right',[({'unknown':1},{'unknown':0}),({'status':'unknown'},{'status':'known'}),
                                      ([1],[1,2]),({'margin':1.},{'margin':1.001}),
                                      ({'x':True},{'x':1}),({'x':float('nan')},{'x':float('nan')})])
def test_compare_rejects_changed_science(left,right):
    with pytest.raises(ValueError):reproduce.compare(left,right)


def test_compare_accepts_declared_roundoff():
    reproduce.compare({'value':1.0,'status':'unknown'},{'value':1.0000001,'status':'unknown'})


def test_source_archive_recovers_portable_inputs(tmp_path):
    path=tmp_path/'source.zip';archive_sources(ROOT,path)
    with zipfile.ZipFile(path) as archive:
        for name in ['reproduction/input-manifest.json','reproduction/inputs/e4/Q0-grid.npy',
                     'requirements-reproduce.lock','scripts/replay_reproduction.py']:
            assert archive.read(name)==(ROOT/name).read_bytes()


def test_bootstrap_tamper_retains_failure_without_environment(tmp_path):
    spec=importlib.util.spec_from_file_location('replay',ROOT/'scripts/replay_reproduction.py')
    replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)
    bundle=tmp_path/'bundle';bundle.mkdir()
    (bundle/'source.zip').write_bytes(b'changed')
    (bundle/'bundle-manifest.json').write_text(json.dumps({'files':{'source.zip':'sha256:'+'0'*64}}))
    output=tmp_path/'attempt'
    with pytest.raises(ValueError):replay.replay(bundle,output)
    assert json.loads((output/'bootstrap.json').read_text())['status']=='failed'
    assert not (output/'venv').exists()
    with pytest.raises(FileExistsError):replay.replay(bundle,output)
