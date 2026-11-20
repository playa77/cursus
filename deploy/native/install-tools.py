#!/usr/bin/env python3
"""Install the four native apps into a credential-free image; no model requests.

Official distribution references and review rationale: ADR 0011.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import urllib.request

PREFIX=Path('/opt/cursus-native')
PACKAGES={'claude':'@anthropic-ai/claude-code','codex':'@openai/codex',
          'pi':'@earendil-works/pi-coding-agent'}


def fetch(url, maximum=1024*1024):
    if not url.startswith('https://'):
        raise RuntimeError('Native download must use HTTPS')
    with urllib.request.urlopen(url,timeout=30) as response:
        value=response.read(maximum+1)
    if len(value)>maximum:
        raise RuntimeError('Download exceeds size bound')
    return value


def install():
    version=subprocess.check_output(['node','--version'],text=True).strip().lstrip('v')
    if tuple(map(int,version.split('.')[:2]))<(22,19):
        raise RuntimeError('Native apps require Node.js 22.19 or newer')
    env={**os.environ,'npm_config_fetch_retries':'0','npm_config_maxsockets':'1',
         'npm_config_fetch_timeout':'30000','npm_config_audit':'false','npm_config_fund':'false'}
    manifest={'node':version,'packages':{}}
    for cli,package in PACKAGES.items():
        print('Installing native '+cli+' from '+package,flush=True)
        version=json.loads(subprocess.check_output(['npm','view',package,'version','--json'],env=env,text=True,timeout=60))
        if not isinstance(version,str) or not all(c.isalnum() or c in '.-+' for c in version):
            raise RuntimeError('Invalid native package version')
        time.sleep(1)
        argv=['npm','install','--global','--prefix',str(PREFIX),package+'@'+version]
        if cli=='pi':argv.append('--ignore-scripts')
        subprocess.run(argv,env=env,check=True,timeout=600)
        manifest['packages'][cli]={'package':package,'version':version}
        time.sleep(1)
    arch={'x86_64':'amd64','aarch64':'arm64'}[os.uname().machine]
    metadata=json.loads(fetch('https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/linux_'+arch+'.json'))
    time.sleep(1)
    payload=fetch(metadata['url'],256*1024*1024)
    if hashlib.sha512(payload).hexdigest()!=metadata['sha512']:
        raise RuntimeError('Antigravity artifact checksum mismatch')
    with tempfile.TemporaryFile() as stream:
        stream.write(payload);stream.seek(0)
        with tarfile.open(fileobj=stream) as archive:
            entry=archive.getmember('antigravity')
            if not entry.isfile() or entry.size>256*1024*1024:
                raise RuntimeError('Unexpected Antigravity archive entry')
            (PREFIX/'bin/agy').write_bytes(archive.extractfile(entry).read())
    (PREFIX/'bin/agy').chmod(0o755)
    manifest['packages']['agy']=metadata
    for cli in ('claude','codex','agy','pi'):
        binary=PREFIX/'bin'/cli
        observed=subprocess.check_output([str(binary),'--version'],text=True,timeout=30).strip()
        manifest['packages'][cli].update(observed_version=observed,binary_digest=hashlib.sha256(binary.read_bytes()).hexdigest())
    (PREFIX/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Installed all four native CLIs. No login or provider inference occurred.',flush=True)


if __name__=='__main__':install()
