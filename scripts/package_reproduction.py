"""Create an exclusive, offline source/data/wheel reproduction bundle."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

from satellite_coverage.io.run_record import archive_sources, environment_record, write_json
from satellite_coverage.data_sources.manifest import checksum_sha256


def package(output, wheel_dirs, baseline):
    root=Path(__file__).resolve().parents[1]
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    baseline=Path(baseline)
    if json.loads((baseline/'validation.json').read_text())['status']!='passed':
        raise ValueError('baseline workflow has not passed')
    for name,digest in json.loads((baseline/'artifacts.json').read_text())['files'].items():
        if checksum_sha256(baseline/name)!=digest:
            raise ValueError('baseline artifact hash mismatch: '+name)
    shutil.copyfile(baseline/'semantic.json',output/'expected.json')
    shutil.copyfile(root/'scripts/replay_reproduction.py',output/'replay_reproduction.py')
    shutil.copyfile(root/'reproduction/README.md',output/'README.md')
    archive_sources(root,output/'source.zip')
    lock=root/'requirements-reproduce.lock'
    wanted=set(re.findall(r'--hash=sha256:([a-f0-9]{64})',lock.read_text()))
    wheels=output/'wheels';wheels.mkdir()
    found=set()
    for directory in wheel_dirs:
        for wheel in sorted(Path(directory).glob('*.whl')):
            digest=hashlib.sha256(wheel.read_bytes()).hexdigest()
            if digest in wanted and digest not in found:
                shutil.copyfile(wheel,wheels/wheel.name);found.add(digest)
    if found!=wanted:
        write_json(output/'failure.json',dict(reason='missing locked wheels',hashes=sorted(wanted-found)))
        raise ValueError('missing locked wheels; incomplete bundle retained')
    write_json(output/'source-environment.json',environment_record(root))
    files={str(p.relative_to(output)):checksum_sha256(p) for p in output.rglob('*') if p.is_file()}
    write_json(output/'bundle-manifest.json',dict(schema_version=1,files=files))
    print(json.dumps(dict(output=str(output),files=len(files),bytes=sum(p.stat().st_size for p in output.rglob('*') if p.is_file()))))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--wheel-dir',required=True,action='append',type=Path)
    parser.add_argument('--baseline',required=True,type=Path)
    args=parser.parse_args();package(args.output,args.wheel_dir,args.baseline)
