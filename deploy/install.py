#!/usr/bin/env python3
"""Guided host installation behind install.sh, revision 2026-11-20-r5.

ADR 0010: source acquisition, host preparation and dependency acquisition precede
configuration. ADR 0011 governs native checks; ADR 0012 governs discovered inputs.
"""
import argparse
import getpass
from hashlib import sha256
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shlex
import shutil
import tempfile
import time
import subprocess
import sys
import tomllib
from types import SimpleNamespace
from urllib.parse import quote, urlsplit

from setup import Installer, log


sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'src'))
from cursus.contracts import Problem


def toml_text(value):
    """Serialize the small config vocabulary without a new runtime dependency."""
    lines = []
    def scalar(item):
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=False)
        if type(item) is bool:
            return str(item).lower()
        if type(item) is int:
            return str(item)
        if isinstance(item, list):
            return '[' + ', '.join(scalar(x) for x in item) + ']'
        if isinstance(item, dict):
            return '{' + ', '.join(json.dumps(k)+ ' = '+scalar(v) for k,v in item.items()) + '}'
        raise ValueError('Unsupported TOML value')
    def table(item, path=(), header=None):
        if header:
            lines.append(header)
        for key, val in item.items():
            if not isinstance(val, dict) and not (isinstance(val,list) and val and isinstance(val[0],dict)):
                lines.append(json.dumps(key)+' = '+scalar(val))
        for key, val in item.items():
            name = '.'.join(json.dumps(x) for x in (*path,key))
            if isinstance(val,dict):
                table(val,(*path,key),'['+name+']')
            elif isinstance(val,list) and val and isinstance(val[0],dict):
                for entry in val:
                    table(entry,(*path,key),'[['+name+']]')
    table(value)
    text = '\n'.join(lines)+'\n'
    if tomllib.loads(text) != value:
        raise ValueError('Config serialization mismatch')
    return text


def write_private(path, data, user=None):
    """Create a named file; existing secrets are deliberately never replaced."""
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd,'w') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    if user:
        account = pwd.getpwnam(user)
        os.chown(path,account.pw_uid,account.pw_gid)


def clean_checkout(source):
    changed = subprocess.check_output(['git','-c','safe.directory='+str(source),'-C',str(source),'status','--porcelain'],text=True)
    if changed.strip():
        raise RuntimeError('Source checkout has local changes. Use a new --source-dir; existing work is never reset.')
    return subprocess.check_output(['git','-c','safe.directory='+str(source),'-C',str(source),'rev-parse','HEAD'],text=True).strip()


class Terminal:
    # Separate streams: a tty is not seekable, unlike an r+ BufferedRandom file.
    def __init__(self):
        self.reader = open('/dev/tty','r')
        self.writer = open('/dev/tty','w')

    def write(self, text):
        return self.writer.write(text)

    def flush(self):
        return self.writer.flush()

    def readline(self):
        return self.reader.readline()


class Guide:
    def __init__(self,args):
        self.args = args
        self.source = Path(args.source).resolve(strict=True)
        self.user = 'cursus-runner' if args.host == 'worker' else 'cursus-control'
        self.root = Path('/etc/cursus')
        self.tty = None if args.non_interactive else Terminal()

    def ask(self,question,default=None):
        if not self.tty:
            raise RuntimeError('Missing prerequisite: '+question+'. Run interactively or prepare the documented file first.')
        while True:
            self.tty.write('\n'+question+'\n'+(f'Press Enter to use {default}.\n' if default is not None else '')+'Your answer: ')
            self.tty.flush()
            line = self.tty.readline()
            if not line:
                raise RuntimeError('Terminal closed; installation incomplete.')
            value = line.strip() or default
            if value is not None and str(value):
                return str(value)

    def choose(self, title, choices):
        """Ask for an authorization/role choice, never a transcription of facts."""
        if not choices:
            raise RuntimeError(title+' No candidates were discovered. Check enrollment and access, then rerun.')
        while True:
            answer = self.ask(title+'\n'+'\n'.join(f'  {i}. {label}' for i,(label,_) in enumerate(choices,1))+'\nEnter a number.')
            if answer.isdecimal() and 1 <= int(answer) <= len(choices):
                return choices[int(answer)-1][1]

    def tailscale(self):
        if not hasattr(self, '_tailscale'):
            try:
                result = subprocess.run(['tailscale','status','--json'],check=True,
                                        capture_output=True,text=True,timeout=15)
                status = json.loads(result.stdout)
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                raise RuntimeError('Cannot read Tailscale status. Install/start Tailscale and enroll this server with sudo tailscale up, then rerun. No manual URL is needed.') from exc
            if status.get('BackendState') != 'Running' or not status.get('Self',{}).get('DNSName'):
                raise RuntimeError('Tailscale is not enrolled and running with a DNS name. Complete sudo tailscale up and enable MagicDNS, then rerun.')
            self._tailscale = status
        return self._tailscale

    @staticmethod
    def node_name(node):
        name = node.get('DNSName','').rstrip('.')
        if not re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+',name):
            raise RuntimeError('Tailscale did not supply a valid full DNS name. Check MagicDNS, then rerun.')
        return name

    def repository(self):
        while True:
            value = self.ask('Which GitHub repository may Cursus work on?\nPaste its GitHub page URL, for example https://github.com/alice/project.\nThe installer extracts the owner and repository name; do not supply a token in the URL.')
            parsed = urlsplit(value)
            parts = parsed.path.strip('/').split('/')
            if parsed.scheme == 'https' and parsed.netloc == 'github.com' and len(parts) == 2 and not parsed.query and not parsed.fragment:
                owner,name = parts
                name = name.removesuffix('.git')
                if re.fullmatch(r'[A-Za-z0-9-]+',owner) and re.fullmatch(r'[A-Za-z0-9_.-]+',name) and name not in ('.','..'):
                    return dict(owner=owner,name=name)
            self.tty.write('Use a repository page URL such as https://github.com/alice/project.\n')
            self.tty.flush()

    def resource_summary(self):
        memory = dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
        total = int(memory['MemTotal'].split()[0]) // 1024
        available = int(memory['MemAvailable'].split()[0]) // 1024
        free = shutil.disk_usage('/var/lib/cursus-runner').free // (1024*1024)
        self.tty.write(f'\nWorker resources detected automatically:\n  RAM: {total} MiB total, {available} MiB currently available\n  CPU: {os.cpu_count() or 1} logical cores\n  Runner disk: {free} MiB free\nChoose workload limits below; current free resources do not establish safe limits for your workload.\n')
        self.tty.flush()

    def controller_origin(self):
        nodes = list(self.tailscale().get('Peer',{}).values())
        choices = [(self.node_name(node), 'https://'+self.node_name(node))
                   for node in nodes if node.get('DNSName')]
        return self.choose('Which Tailscale server will run the controller website and database?\nThese names were read automatically. Choose server B; it need not have Cursus installed yet.', sorted(choices))

    def operator_login(self):
        users = self.tailscale().get('User',{})
        choices = sorted({user['LoginName'] for user in users.values() if user.get('LoginName')})
        return self.choose('Which Tailscale account may operate Cursus?\nChoose your browser login. This grants website access; the server owner is not assumed to be the operator.',[(login,login) for login in choices])

    def roles(self, raw, profile):
        registry = tomllib.loads((self.source/'roles.toml').read_text())
        registry['profile_digest'] = sha256(raw).hexdigest()
        for name,role in registry['roles'].items():
            base = profile[role['cli']]
            effective = dict(base,**base.get('role_profiles',{}).get(name,{}))
            if name not in effective['qualified_roles'] or set(role['tools']) != set(effective['tool_allowlist']):
                raise RuntimeError('Measured role/tool coverage missing for '+name+'; fix qualification before installation.')
            for field in ('model','reasoning','provider'):
                if field in effective:
                    role[field] = effective[field]
                else:
                    role.pop(field,None)
        prompts = sorted((self.source/'prompts').glob('*.md'))
        if (self.source/'prompts').is_symlink() or any(p.is_symlink() or not p.is_file() for p in prompts):
            raise RuntimeError('Prompt release must contain regular files within the source tree.')
        text = toml_text(registry)
        # Content-addressed independent role Git releases avoid dirtying source,
        # committing host inventory, or mutating files used by an active release.
        identity = sha256(text.encode()+b''.join(p.name.encode()+b'\0'+p.read_bytes()+b'\0' for p in prompts)).hexdigest()
        root = self.root/'roles'/identity
        if not root.exists():
            root.parent.mkdir(exist_ok=True,mode=0o755)
            root.parent.chmod(0o755)
            root.mkdir(mode=0o755)
            root.chmod(0o755)
            (root/'roles.toml').write_text(text)
            (root/'prompts').mkdir(mode=0o755)
            for prompt in prompts:
                (root/'prompts'/prompt.name).write_bytes(prompt.read_bytes())
            for argv in (['init','--quiet'], ['add','--','roles.toml','prompts'],
                         ['-c','user.name=Cursus installer','-c','user.email=cursus@localhost',
                          '-c','commit.gpgsign=false','-c','core.hooksPath=/dev/null',
                          'commit','--quiet','-m','Pin qualified deployment roles and prompts']):
                subprocess.run(['git','-C',str(root),*argv],check=True)
        commit = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
        return root,commit

    def fill(self,value,path=()):
        descriptions = {
            'external_origin': 'Controller website address. Use the private HTTPS URL of server B, without a trailing slash.',
            'origin': 'Controller website address. Use the private HTTPS URL of server B, without a trailing slash.\nOn B, run: tailscale status --json\nRead Self.DNSName, remove its final dot, and prefix it with https://.\nExample: controller.example.ts.net. becomes https://controller.example.ts.net\nThis identifies the address; HTTPS must still be enabled with Tailscale Serve. Do not use this worker address.',
            'operator_login': 'Who may operate the website? Enter your exact Tailscale account login, usually an email address.\nFind it in the Tailscale admin console Users page. Use the account you will use in your browser, not a display name or the server owner unless that is you.',
            'tailnet_node': 'Worker identity. Enter the full server A Tailscale DNS name, without the final dot.\nOn A, run tailscale status --json and read Self.DNSName. This is the worker, not the controller.',
            'owner': 'GitHub repository owner. For https://github.com/alice/project, enter alice.\nUse the user or organization that owns the repository Cursus is allowed to work on.',
            'name': 'GitHub repository name. For https://github.com/alice/project, enter project.\nDo not include the owner, URL, or .git suffix.',
            'image': 'Execution image ID. Obtain it from podman image inspect for your qualified image.\nUse sha256: followed by 64 hexadecimal digits. Guided native setup generates this automatically.',
            'worker': 'Maximum simultaneous pi sessions, from 1 to 4, including scout and debug sessions.\nChoose a ceiling your provider account and worker resources can support. Each slot requires its own native login domain.',
            'claude': 'Maximum simultaneous Claude Code sessions, from 1 to 2.\nChoose a ceiling allowed by your account and resources. Each slot requires a native login.',
            'codex': 'Maximum simultaneous Codex sessions, from 1 to 2.\nChoose a ceiling allowed by your account and resources. Each slot requires a native login.',
            'agy': 'Maximum simultaneous Antigravity sessions, from 1 to 2.\nChoose a ceiling allowed by your account and resources. Each slot requires a native login.',
            'memory_mb': 'Memory limit in MiB (1024 MiB = 1 GiB). Enter a positive whole number.\nUnder containers.budget this is the total execution allowance; under resources.agent or resources.verifier it is the limit for ONE container.\nUse the detected memory shown above. Choose workload limits, leaving the host reserve outside the total budget.',
            'cpu_millis': 'CPU allowance in thousandths of a core: 1000 = one core, 2000 = two cores.\nUnder containers.budget this is the total allowance; under resources it applies to ONE container.\nUse the detected CPU count shown above. Leave the host CPU reserve outside the total budget.',
            'pids': 'Process and thread limit, as a positive whole number.\nUnder containers.budget this is the total scheduled allowance; under resources it is the limit for ONE container.\nChoose enough for your tools and test subprocesses; inspect a representative workload rather than copying an arbitrary value.',
            'tmp_mb': 'Maximum disposable /tmp size for ONE container, in MiB.\nChoose enough for temporary files created by your tools/tests. This is memory-backed storage and must fit your memory plan.',
            'home_mb': 'Maximum disposable home-directory size for ONE container, in MiB.\nChoose enough for runtime caches and temporary settings. Persistent native login state is stored separately. Account for memory-backed storage.',
            'host_reserve_mb': 'Memory reserved for Ubuntu, Podman and other host services, in MiB.\nUse the detected RAM shown above and the needs of your host services. Total execution memory plus this reserve must fit physical RAM.',
            'host_reserve_cpu_millis': 'CPU reserved for host services, in thousandths of a core (1000 = one core).\nUse the detected core count shown above. Total execution CPU plus this reserve must fit the available cores.',
            'disk_reserve_mb': 'Minimum free disk space in MiB before Cursus stops starting new containers.\nUse the detected free disk shown above. Choose a safety margin for images, repositories, logs and the operating system.',
            'off_host_destination': 'Your independently managed backup destination outside server B.\nEnter the destination used by your backup procedure, for example a private backup host and path.\nCursus records this value but does not create the destination, copy backups or schedule them. Arrange and verify backups separately.',
        }
        if isinstance(value,dict):
            return {k:self.fill(v,(*path,k)) for k,v in value.items()}
        if isinstance(value,list):
            return [self.fill(v,(*path,str(i))) for i,v in enumerate(value)]
        if isinstance(value,str) and 'REPLACE_' in value:
            key = path[-1]
            answer = self.ask('Setting: '+'.'.join(path)+'\n'+descriptions[key])
            if key in {'worker','claude','codex','agy','memory_mb','cpu_millis','pids','tmp_mb','home_mb','host_reserve_mb','host_reserve_cpu_millis','disk_reserve_mb'}:
                return int(answer)
            return answer
        return value

    def configure(self):
        kind = 'runner' if self.args.host=='worker' else 'control'
        target = self.root/(kind+'.toml')
        if target.exists() or target.is_symlink():
            if target.is_symlink():
                raise RuntimeError('Refusing symlink config: '+str(target))
            log('Reusing explicit host config '+str(target)+'; it will be validated, not overwritten.')
            return target
        log('[3/5] Configuring this server. Each question explains what to enter and where to find it.')
        from native_setup import NativeSetup, read_pairing
        config = tomllib.loads((self.source/'deploy'/f'{kind}.example.toml').read_text())
        status = self.tailscale()
        if kind=='control':
            bundle = read_pairing(self.ask('Paste the pairing code generated by the worker installer (no credentials)'))
            raw = bundle['profile'].encode()
            profile = tomllib.loads(raw.decode())
            from cursus.config import capability
            if profile.get('schema_version')!=2 or profile.get('qualification') not in ('qualified','native-checked'):
                raise RuntimeError('Worker pairing is not from completed native setup checks.')
            for cli in ('claude','codex','agy','pi'):
                capability(cli,profile[cli])
            worker = bundle['config']
            local_origin = 'https://'+self.node_name(status['Self'])
            if worker['service']['origin'] != local_origin:
                raise RuntimeError('The worker pairing code names a different controller. Run this on the selected server B, or reconfigure the worker for this controller.')
            config['service']['operator_login'] = self.operator_login()
            worker_node = worker['service'].get('tailnet_node')
            if worker_node:
                config['runner']['tailnet_node'] = worker_node
            else:
                peers = [self.node_name(n) for n in status.get('Peer',{}).values() if n.get('DNSName')]
                config['runner']['tailnet_node'] = self.choose('Select the worker server for this older pairing code.',[(n,n) for n in sorted(peers)])
            root,commit = self.roles(raw,profile)
            config['service'].update(roles_file=str(root/'roles.toml'),prompts_root=str(root/'prompts'),
                                     role_release_commit=commit,external_origin=worker['service']['origin'])
            config['runner']['id'] = worker['service']['runner_id']
            config['capacity'] = worker['capacity']
            config['repositories'] = worker['repositories']
            self.pending_bearer_digest = bundle['bearer_digest']
        else:
            config['service']['origin'] = self.controller_origin()
            self.resource_summary()
            config['repositories'][0].update(self.repository())
            config['service']['runner_id'] = str(__import__('uuid').uuid4())
            config['service']['capabilities_digest'] = 'generated-by-installer'
            config['containers']['image'] = 'generated-by-installer'
            config['containers']['credentials'] = {}
            config['containers']['version'] = subprocess.check_output(['podman','--version'],text=True).strip().removeprefix('podman version ')
            config['containers']['native_keyring'] = True
            config['containers']['hide_project_customizations'] = True
        config = self.fill(config)
        # The controller template historically used a host venv path. Checks
        # always refer to binaries in the image, on both sides of enrollment.
        if kind=='runner':
            check = config['repositories'][0]['checks'][0]
            check['argv'] = json.loads(self.ask('Repository test command. Read the repository README or CI workflow for its actual test command.\nEnter a JSON list of arguments, using an absolute executable path INSIDE the execution image.\nThe example only applies to repositories with Python unittest tests in tests/unit.', '["/usr/bin/python3", "-m", "unittest", "discover", "-s", "tests/unit"]'))
            target = self.ask('Which branch may Cursus target in that repository?\nChoose the intended branch in GitHub. Enter its name, such as main.','main')
            config['repositories'][0]['allowed_target_refs'] = [target if target.startswith('refs/heads/') else 'refs/heads/'+target]
        if kind=='runner':
            profile = NativeSetup(self,config).run()
            raw = toml_text(profile).encode()
            digest = sha256(raw).hexdigest()
            destination = Path('/etc/cursus/runner')/('capabilities-'+digest+'.toml')
            if not destination.exists():
                write_private(destination,raw.decode(),self.user)
            elif destination.is_symlink() or destination.read_bytes()!=raw:
                raise RuntimeError('Generated capability file conflicts with existing state.')
            config['service'].update(capabilities_file=str(destination),capabilities_digest=digest)
        write_private(target,toml_text(config),self.user)
        log('Saved private config '+str(target))
        if kind=='control':
            log('Paired runner UUID: '+config['runner']['id'])
        return target

    def secrets(self,config):
        service = config['service']
        if self.args.host=='controller':
            dsn = Path(service['dsn_file'])
            if dsn.is_symlink():
                raise RuntimeError('Refusing symlink DSN file.')
            if not dsn.exists():
                write_private(dsn,'postgresql:///cursus?host=/var/run/postgresql\n',self.user)
            digest = Path(config['runner']['bearer_digest_file'])
            if digest.is_symlink():
                raise RuntimeError('Refusing symlink digest file.')
            if not digest.exists():
                value = getattr(self,'pending_bearer_digest',None) or self.ask('Runner bearer SHA-256 digest from A (64 hex characters)')
                if not re.fullmatch('[0-9a-f]{64}',value):
                    raise RuntimeError('Expected the digest, not the secret bearer.')
                write_private(digest,value+'\n',self.user)
        else:
            bearer = Path(service['bearer_file'])
            if bearer.is_symlink():
                raise RuntimeError('Refusing symlink bearer file.')
            if not bearer.exists():
                write_private(bearer,secrets.token_urlsafe(48)+'\n',self.user)
            # Consume only the program-owned approved bearer; never display it.
            log('Bearer SHA-256 for B: '+sha256(bearer.read_text().strip().encode()).hexdigest())
            from native_setup import pairing_code
            profile = Path(service['capabilities_file']).read_text()
            metadata = dict(service=dict({key:service[key] for key in ('runner_id','origin')},
                                         tailnet_node=self.node_name(self.tailscale()['Self'])),
                            capacity=config['capacity'],repositories=config['repositories'])
            bundle = dict(format=1,config=metadata,profile=profile,bearer_digest=sha256(bearer.read_text().strip().encode()).hexdigest())
            log('WORKER PAIRING CODE — paste into the controller installer (contains no credentials):')
            print(pairing_code(bundle),flush=True)
            publisher = config['publisher']
            if any(Path(publisher[k]).is_symlink() for k in ('git_credential_file','github_credential_file')):
                raise RuntimeError('Refusing symlink publisher credential file.')
            missing = [Path(publisher[k]) for k in ('git_credential_file','github_credential_file') if not Path(publisher[k]).exists()]
            if missing:
                if not self.tty:
                    raise RuntimeError('Publisher credential files missing. Provision the two documented private files before unattended installation.')
                self.tty.write('GitHub publisher token\nIn GitHub Settings > Developer settings > Personal access tokens, create a dedicated fine-grained token for the enrolled repository.\nGrant repository Contents: read/write and Pull requests: read/write, and obtain organization approval if required. Branch protections still apply.\nPaste the token below. Input is hidden; do not paste it into a shell command.\n'); self.tty.flush()
                token = getpass.getpass('Publisher token: ',stream=self.tty)
                if not token or any(x in token for x in '\r\n'):
                    raise RuntimeError('Invalid empty/multiline publisher token.')
                for key in ('git_credential_file','github_credential_file'):
                    path = Path(publisher[key])
                    if path in missing:
                        content = token if key=='github_credential_file' else 'https://x-access-token:'+quote(token,safe='')+'@github.com'
                        write_private(path,content+'\n',self.user)

    def require_native_mounts(self, config):
        if self.args.host != 'worker':
            return
        uid = pwd.getpwnam(self.user).pw_uid
        for domains in config['containers']['credentials'].values():
            for domain in domains:
                for mount in domain['mounts']:
                    path = Path(mount['source'])
                    if path.is_symlink() or not path.is_dir():
                        raise RuntimeError('Native login prerequisite missing: '+str(path)+
                                           '. Provision the qualified auth-only domain before activation; no service started.')
                    info = path.stat()
                    if info.st_uid != uid or info.st_mode & 0o077:
                        raise RuntimeError('Native auth domain must be private (0700) and owned by '+self.user+': '+str(path))

    def run(self):
        if getattr(self.args,'native_only',False) and (self.args.host!='worker' or self.args.activate_existing):
            raise RuntimeError('--native-only is for initial worker setup and conflicts with activation.')
        if os.geteuid()!=0:
            raise RuntimeError('Run through install.sh; host setup needs authorized sudo.')
        os_release = Path('/etc/os-release').read_text()
        if 'ID=ubuntu' not in os_release or 'VERSION_ID="26.04"' not in os_release:
            raise RuntimeError('This installer requires Ubuntu Server 26.04.')
        release = clean_checkout(self.source)
        options = SimpleNamespace(host=self.args.host,release=release,config=self.args.config,
                                  wheelhouse=self.args.wheelhouse,apply=True,activate=False,activate_existing=self.args.activate_existing)
        installer = Installer(options)
        if options.config and not self.args.activate_existing:
            options.apply = False
            installer.preflight()
            options.apply = True
        if self.args.activate_existing:
            if not self.args.config:
                raise RuntimeError('--activate-existing requires the exact saved --config.')
            options.activate = True
            installer.preflight()
            self.require_native_mounts(tomllib.loads(Path(self.args.config).read_text()))
            installer.activate()
            return
        log('[3/5] Preparing stable service account, database/runtime and private storage...')
        installer.prepare_host()
        config_path = Path(self.args.config).resolve(strict=True) if self.args.config else self.configure()
        if config_path.is_symlink():
            raise RuntimeError('Config must not be a symlink.')
        config = tomllib.loads(config_path.read_text())
        options.config = str(config_path)
        self.secrets(config)
        if getattr(self.args,'native_only',False):
            log('Native tools, login checks and private config prepared; no Cursus release staged or activated.')
            return
        log('[4/5] Preparing hash-locked Python dependencies and immutable release...')
        if not options.wheelhouse:
            # An isolated bootstrap venv owned by root. pip's configured retry
            # layer is disabled; one download batch, timeout 30s per connection.
            build = Path('/opt/cursus/bootstrap')
            if build.is_symlink():
                raise RuntimeError('Refusing symlink bootstrap environment.')
            subprocess.run(['python3','-m','venv',str(build/'venv')],check=True)
            wheels = build/'wheels'
            wheels.mkdir(exist_ok=True)
            # 21 locked distributions currently: one package at a time with a
            # one-second gap, no pip retries, and a ten-minute total budget.
            deadline = time.monotonic()+600
            entries = [block for block in (self.source/'requirements.lock').read_text().split('\n\n')
                       if block.strip() and not block.lstrip().startswith('#')]
            log(f'Downloading {len(entries)} locked packages: one process at a time, 1s gaps, no retries, 10 minute budget.')
            for index,entry in enumerate(entries):
                remaining = deadline-time.monotonic()
                if remaining<=0:
                    raise RuntimeError('Dependency download time budget exhausted; reuse downloaded wheels on resume.')
                with tempfile.NamedTemporaryFile(mode='w',suffix='.txt') as requirement:
                    requirement.write(entry+'\n'); requirement.flush()
                    subprocess.run([str(build/'venv/bin/python'),'-m','pip','--isolated','download','--no-deps',
                                    '--retries','0','--timeout','30','--disable-pip-version-check',
                                    '--require-hashes','--only-binary=:all:', '--dest',str(wheels),'-r',requirement.name],
                                   check=True,timeout=remaining)
                if index+1<len(entries):
                    time.sleep(1)
            options.wheelhouse = str(wheels)
        installer = Installer(options)
        installer.preflight()
        installer.stage(prepared=True)
        if self.args.stage_only:
            log('STAGED, NOT ACTIVE: '+str(installer.release))
            log('Resume using install.sh --host '+self.args.host+' --config '+shlex.quote(str(config_path))+' --activate-existing')
            return
        self.require_native_mounts(config)
        log('[5/5] Validating and activating (existing deployments require drain)...')
        installer.activate()
        log('Service started. Check authenticated readiness in README; no provider qualification was performed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',required=True,choices=('controller','worker'))
    parser.add_argument('--source',required=True)
    parser.add_argument('--config')
    parser.add_argument('--wheelhouse')
    parser.add_argument('--native-only',action='store_true')
    parser.add_argument('--stage-only',action='store_true')
    parser.add_argument('--activate-existing',action='store_true')
    parser.add_argument('--non-interactive',action='store_true')
    args = parser.parse_args()
    try:
        os.umask(0o022)
        Guide(args).run()
        return 0
    except (OSError,ValueError,KeyError,RuntimeError,Problem,KeyboardInterrupt,subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
        # Child command output carries progress; never dump configs or tokens.
        message = 'A child command failed; inspect its output above.' if isinstance(exc,(subprocess.CalledProcessError,subprocess.TimeoutExpired)) else str(exc)
        log('INSTALLATION INCOMPLETE: '+message)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
