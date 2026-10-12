"""Stdlib-only offline bootstrap; run directly from a reproduction bundle."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile


def replay(bundle, output):
    bundle=Path(bundle).resolve(); output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    status=output/'bootstrap.json'
    status.write_text(json.dumps(dict(status='running')))
    try:
        if sys.version_info[:2]!=(3,12) or sys.platform!='linux' or platform.machine()!='x86_64':
            raise ValueError('locked supported target is CPython 3.12 Linux x86_64')
        manifest=json.loads((bundle/'bundle-manifest.json').read_text())
        for name, expected in manifest['files'].items():
            if Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError('unsafe bundle manifest path')
            actual='sha256:'+hashlib.sha256((bundle/name).read_bytes()).hexdigest()
            if actual!=expected:raise ValueError('bundle hash mismatch: '+name)
        source=output/'source'; source.mkdir()
        with zipfile.ZipFile(bundle/'source.zip') as archive:
            for item in archive.infolist():
                if Path(item.filename).is_absolute() or '..' in Path(item.filename).parts:
                    raise ValueError('unsafe source archive path')
            archive.extractall(source)
        env=dict(os.environ,PYTHONNOUSERSITE='1',PIP_DISABLE_PIP_VERSION_CHECK='1',PIP_NO_INDEX='1')
        for key in ('PROJ_DATA','PROJ_LIB','GDAL_DATA','PYTHONPATH','PYTHONHOME','PYTHONUSERBASE'):
            env.pop(key,None)
        def command(args,name,cwd=source):
            with (output/(name+'.log')).open('w') as log:
                subprocess.run(list(map(str,args)),cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
            print(name+' passed',flush=True)
        command([sys.executable,'-m','venv',output/'venv'],'venv')
        python=output/'venv/bin/python'
        command([python,'-m','pip','install','--no-index','--no-cache-dir','--find-links',bundle/'wheels',
                 '--require-hashes','-r',source/'requirements-reproduce.lock'],'dependencies')
        command([python,'-m','pip','install','--no-index','--no-deps','--no-build-isolation','-e',source],'install')
        command([python,'-m','pip','check'],'dependency-check')
        command([python,'-m','pytest','tests','-q'],'tests')
        command([python,'scripts/reproduce_small.py','--output',output/'run','--expected',bundle/'expected.json'],'workflow')
        status.write_text(json.dumps(dict(status='passed',bundle=str(bundle),source=str(source),python=str(python),
            system_site_packages=False,network_required=False),indent=2)+'\n')
    except Exception as exc:
        status.write_text(json.dumps(dict(status='failed',error=str(exc)),indent=2)+'\n')
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();replay(args.bundle,args.output)
