#!/usr/bin/env python3
"""Install the four native apps into a credential-free image; no model requests.

Revision 2026-11-20-r2. Official distribution references and rationale: ADR 0011.
"""
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import urllib.request

# Compressed transfer and expanded executable sizes have different bounds.
ARCHIVE_MAX_BYTES=256*1024*1024
BINARY_MAX_BYTES=512*1024*1024
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



def unpack_antigravity(payload, destination):
    """Copy only the expected executable; never extract archive paths or links."""
    with tempfile.TemporaryFile() as stream:
        stream.write(payload);stream.seek(0)
        with tarfile.open(fileobj=stream) as archive:
            try:
                entry=archive.getmember('antigravity')
            except KeyError:
                raise RuntimeError('Antigravity archive is missing its antigravity executable') from None
            if not entry.isfile():
                raise RuntimeError('Antigravity archive entry must be a regular file')
            if not 0 < entry.size <= BINARY_MAX_BYTES:
                raise RuntimeError(f'Antigravity executable size {entry.size} bytes is outside the allowed 1–{BINARY_MAX_BYTES} bytes')
            with archive.extractfile(entry) as source, destination.open('wb') as output:
                shutil.copyfileobj(source,output,length=1024*1024)


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
    print('Installing native agy from the official Antigravity archive',flush=True)
    payload=fetch(metadata['url'],ARCHIVE_MAX_BYTES)
    if hashlib.sha512(payload).hexdigest()!=metadata['sha512']:
        raise RuntimeError('Antigravity artifact checksum mismatch')
    unpack_antigravity(payload,PREFIX/'bin/agy')
    (PREFIX/'bin/agy').chmod(0o755)
    manifest['packages']['agy']=metadata
    for cli in ('claude','codex','agy','pi'):
        binary=PREFIX/'bin'/cli
        observed=subprocess.check_output([str(binary),'--version'],text=True,timeout=30).strip()
        with binary.open('rb') as stream:
            binary_digest=hashlib.file_digest(stream,'sha256').hexdigest()
        manifest['packages'][cli].update(observed_version=observed,binary_digest=binary_digest)
    (PREFIX/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Installed all four native CLIs. No login or provider inference occurred.',flush=True)


if __name__=='__main__':install()
