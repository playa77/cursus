"""Rootless Podman lifecycle. See ADR 0009; no workflow authority lives here."""
import asyncio
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4
from cursus.contracts import Problem, canonical_json, validate


def utc():
    return datetime.now(timezone.utc).isoformat()


def customization_masks(workspace):
    """Hide executable project discovery without changing repository bytes."""
    masks=[]
    visited=0
    directories={'.agents','.agent','_agents','_agent','.claude','.codex','.pi','.gemini'}
    for root,dirs,files in os.walk(workspace,followlinks=False):
        visited+=1
        if visited>10000 or len(masks)>128:
            raise Problem('mount_boundary','Project customization scan exceeds its bound.')
        dirs[:]=[name for name in dirs if name not in {'.git','node_modules','.venv','__pycache__'}]
        for name in list(dirs):
            if name in directories:
                path=Path(root)/name
                if path.is_symlink():
                    raise Problem('mount_boundary','Project customization directory must not be a symlink.')
                target='/workspace/'+str(path.relative_to(workspace))
                if any(c in target for c in (':',',','\n')):
                    raise Problem('mount_boundary','Unsupported customization mount delimiter.')
                masks.append('--tmpfs='+target+':ro,nosuid,nodev,mode=0555,size=1m')
                dirs.remove(name)
        for name in ('.mcp.json','.claude.json'):
            if name in files:
                path=Path(root)/name
                if path.is_symlink():
                    raise Problem('mount_boundary','Project customization file must not be a symlink.')
                target='/workspace/'+str(path.relative_to(workspace))
                if any(c in target for c in (':',',','\n')):
                    raise Problem('mount_boundary','Unsupported customization mount delimiter.')
                masks.extend(['--volume','/dev/null:'+target+':ro'])
    return masks


class Containers:
    def __init__(self, settings, root, capacity, command=None):
        self.settings, self.capacity = settings, capacity
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.stat().st_uid != os.getuid():
            raise Problem('runtime_identity', 'Lifecycle directory must be owned by the stable runner UID.')
        self.path = self.root / 'containers.json'
        self.entries = json.loads(self.path.read_text()) if self.path.exists() else {}
        if len(self.entries) > 32:
            raise Problem('runtime_state', 'Execution ledger exceeds bounded inventory.')
        self.current = ContextVar('container_execution', default=None)
        self.command = command or self._command
        self.lock = asyncio.Lock()
        self.owned = set()
        self.record = None

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical_json(self.entries))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        fd = os.open(self.root, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def state(self, item, state, reason):
        item.update(state=state, since=utc(), reason=reason)
        self.save()

    @property
    def environment(self):
        # Management environment belongs only to the stable runner account.
        import pwd
        return {'HOME': pwd.getpwuid(os.getuid()).pw_dir, 'PATH': '/usr/bin:/bin',
                'LANG': 'C.UTF-8', 'XDG_RUNTIME_DIR': '/run/user/' + str(os.getuid()),
                'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/' + str(os.getuid()) + '/bus'}

    async def _command(self, *args):
        process = await asyncio.create_subprocess_exec(self.settings['binary'], '--remote=false', '--cgroup-manager=systemd', *args,
            env=self.environment, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            raw, error = await asyncio.wait_for(process.communicate(), 20)
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if len(raw) > 1024 * 1024 or len(error) > 65536:
            raise Problem('runtime_unavailable', 'Runtime diagnostic exceeded its bound.')
        return process.returncode, raw

    def budget(self, lane):
        return self.settings['resources']['verifier' if lane == 'verifier' else 'agent']

    def fits(self, lane):
        resource = self.budget(lane)
        entries = list(self.entries.values())
        if sum(e['lane'] == lane for e in entries) >= self.capacity[lane]:
            return False
        if lane != 'verifier':
            entries = [e for e in entries if e['lane'] != 'verifier']
        for key in ('memory_mb', 'cpu_millis', 'pids'):
            used = sum(e['resources'][key] for e in entries)
            reserved = 0 if lane == 'verifier' else self.budget('verifier')[key] * self.capacity['verifier']
            if used + resource[key] + reserved > self.settings['budget'][key]:
                return False
        available = next(int(line.split()[1]) // 1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
        if available < resource['memory_mb'] + self.settings['budget']['host_reserve_mb']:
            return False
        if shutil.disk_usage(self.root).free < self.settings['disk_reserve_mb'] * 1024 * 1024:
            return False
        return True

    async def preflight(self):
        total = next(int(line.split()[1]) // 1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:'))
        budget = self.settings['budget']
        if budget['memory_mb'] + budget['host_reserve_mb'] > total or budget['cpu_millis'] + budget['host_reserve_cpu_millis'] > (os.cpu_count() or 1)*1000:
            raise Problem('hardware_budget', 'Configured execution plus host reserve exceeds observed host memory/CPU inventory.')
        code, raw = await self.command('--version')
        if code or raw.decode().strip() != 'podman version ' + self.settings['version']:
            raise Problem('runtime_version', 'Installed Podman differs from the qualified exact version.')
        code, raw = await self.command('info', '--format', '{{.Host.CgroupVersion}} {{.Host.CgroupManager}} {{.Host.Security.Rootless}}')
        if code or raw.decode().strip() != 'v2 systemd true':
            raise Problem('runtime_boundary', 'Rootless Podman requires cgroup v2 and the service account user manager.')
        code, _ = await self.command('image', 'exists', self.settings['image'])
        if code:
            raise Problem('runtime_image', 'Qualified execution image is not installed locally; no automatic pull.')

    async def reserve(self, attempt, lane, cli=None):
        validate('Id', attempt)
        async with self.lock:
            if attempt in self.entries:
                raise Problem('state_conflict', 'Execution identity exists; relaunch forbidden.')
            if not self.fits(lane):
                return False
            domain = None
            if cli:
                used = {e.get('domain') for e in self.entries.values()}
                domain = next((d['id'] for d in self.settings['credentials'][cli] if d['id'] not in used), None)
                if domain is None:
                    return False
            self.entries[attempt] = dict(attempt=attempt, name='cursus-' + attempt,
                token=uuid4().hex, id=None, lane=lane, domain=domain, cli=cli,
                resources=self.budget(lane), host_uid=os.getuid(), host_gid=os.getgid(), image=self.settings['image'], created=utc(), state='preparing', since=utc(), reason='Reserved before preparation.')
            self.save()
            if self.record:
                self.record('container_intent', dict(self.entries[attempt]))
            self.owned.add(attempt)
            return True

    async def inspect(self, item):
        if item.get('host_uid') != os.getuid() or item.get('host_gid') != os.getgid() or item.get('image') != self.settings['image']:
            raise Problem('runtime_identity', 'Host identity/image differs from the recorded execution; reconcile before migration.')
        code, raw = await self.command('container', 'exists', item['name'])
        if code == 1:
            return None
        if code:
            raise Problem('runtime_unavailable', 'Cannot establish container existence.')
        code, raw = await self.command('container', 'inspect', item['name'])
        if code:
            raise Problem('runtime_unavailable', 'Cannot inspect execution container.')
        try:
            value, = json.loads(raw)
            identity = value['Id']
            if (not re.fullmatch('[0-9a-f]{64}', identity) or
                    value['Name'].lstrip('/') != item['name'] or
                    value['Config']['Labels'].get('io.cursus.owner') != item['token'] or
                    value['Config'].get('User') != '1000:1000' or
                    value['Image'].removeprefix('sha256:') != item['image'].removeprefix('sha256:') or
                    (item['id'] and item['id'] != identity)):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise Problem('runtime_identity', 'Container identity differs; manual investigation required.') from None
        if item['id'] is None:
            item['id'] = identity
            self.save()
        return value

    async def prepare(self, attempt, workspace, readonly=False):
        item = self.entries[attempt]
        workspace = Path(workspace)
        if workspace.is_symlink() or not workspace.is_absolute() or workspace.stat().st_uid != os.getuid():
            raise Problem('mount_boundary', 'Workspace ownership/path is invalid.')
        r = item['resources']
        argv = ['create', '--pull=never', '--name', item['name'], '--label', 'io.cursus.owner=' + item['token'],
            '--entrypoint=/usr/bin/sleep', '--image-volume=ignore', '--unsetenv-all', '--userns=keep-id:uid=1000,gid=1000', '--user=1000:1000', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--pid=private', '--ipc=private', '--read-only',
            '--cgroup-parent=cursus-execution-' + ('verifier' if item['lane']=='verifier' else 'agents') + '.slice', '--network=' + ('none' if item['lane'] == 'verifier' else self.settings['network']),
            '--memory=' + str(r['memory_mb']) + 'm', '--memory-swap=' + str(r['memory_mb']) + 'm',
            '--cpus=' + str(r['cpu_millis'] / 1000), '--pids-limit=' + str(r['pids']),
            '--tmpfs=/tmp:rw,nosuid,nodev,size=' + str(r['tmp_mb']) + 'm',
            '--tmpfs=/home/session:rw,nosuid,nodev,uid=1000,gid=1000,mode=700,size=' + str(r['home_mb']) + 'm',
            '--env=HOME=/home/session', '--env=PATH=/usr/local/bin:/usr/bin:/bin', '--env=LANG=C.UTF-8',
            '--env=TMPDIR=/tmp', '--workdir=/workspace', '--log-driver=none', '--restart=no',
            '--volume', str(workspace) + ':/workspace:' + ('ro' if readonly else 'rw')]
        if self.settings.get('hide_project_customizations'):
            argv += customization_masks(workspace)
        if item['cli'] == 'agy' and self.settings.get('native_keyring'):
            argv += ['--env=DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/cursus-session-bus',
                     '--env=XDG_RUNTIME_DIR=/tmp/cursus-runtime']
        if (workspace / '.git').is_dir():
            argv += ['--volume', str(workspace / '.git') + ':/workspace/.git:ro']
        if item['cli']:
            domain = next(d for d in self.settings['credentials'][item['cli']] if d['id'] == item['domain'])
            for mount in domain['mounts']:
                source = Path(mount['source'])
                if source.is_symlink() or not source.is_dir() or source.stat().st_uid != os.getuid() or source.stat().st_mode & 0o077:
                    raise Problem('credential_boundary', 'Credential mount must be a private runner-owned directory.')
                argv += ['--volume', str(source) + ':' + mount['target'] + ':rw']
        argv += [self.settings['image'], 'infinity']
        code, raw = await self.command(*argv)
        if code:
            raise Problem('runtime_unavailable', 'Container creation failed; cleanup will inspect intent.')
        value = await self.inspect(item)
        if value is None:
            raise Problem('runtime_unavailable', 'Created execution container is absent.')
        # Immutable ID is fsynced by inspect before the first start effect.
        if self.record:
            self.record('container_identity', dict(item))
        self.state(item, 'starting', 'Container identity recorded before start.')
        code, _ = await self.command('start', item['id'])
        if code:
            raise Problem('runtime_unavailable', 'Container start failed.')
        if item['cli'] == 'agy' and self.settings.get('native_keyring'):
            code, _ = await self.command('exec', item['id'], '/usr/local/bin/cursus-start-keyring')
            if code:
                raise Problem('runtime_unavailable', 'Private native keyring could not start; execution cannot use its login.')
        self.state(item, 'running', 'Native execution may run in the owned container.')

    async def spawn(self, argv, workspace, **kwargs):
        item = self.entries[self.current.get()]
        value = await self.inspect(item)
        if value is None or not value['State']['Running']:
            raise Problem('unknown_stop', 'Execution container is not confirmed running.')
        return await asyncio.create_subprocess_exec(self.settings['binary'], '--remote=false', '--cgroup-manager=systemd', 'exec',
            '--interactive', '--workdir', '/workspace' + (('/' + str(workspace.relative_to(Path(item['workspace'])))) if workspace != Path(item['workspace']) else ''),
            item['id'], *argv, env=self.environment, **kwargs)

    async def cleanup(self, attempt):
        item = self.entries.get(attempt)
        if item is None:
            return True
        try:
            value = await self.inspect(item)
            if value is not None:
                self.state(item, 'stopping', 'Stopping actual container and descendants.')
                code, _ = await self.command('stop', '--time=2', item['id'])
                value = await self.inspect(item)
                if value and value['State']['Running']:
                    raise Problem('unknown_stop', 'Container remains running.')
                self.state(item, 'cleanup', 'Execution stopped; removing disposable state.')
                code, _ = await self.command('rm', item['id'])
                if code or await self.inspect(item) is not None:
                    raise Problem('cleanup_pending', 'Container removal is not confirmed.')
            if self.record:
                self.record('container_removed', attempt)
            del self.entries[attempt]
            self.save()
            self.owned.discard(attempt)
            return True
        except (OSError, ValueError, Problem, TimeoutError):
            self.state(item, 'uncertain', 'Inspect/stop/removal failed; reservation retained. Automatic retry in 10s; inspect runner service diagnostics.')
            return False

    async def recover(self):
        # Only the bounded unresolved inventory; never scan every old attempt.
        results = {}
        for attempt in list(self.entries):
            if attempt not in self.owned:
                results[attempt] = await self.cleanup(attempt)
        return results

    def status(self):
        return [{k:v for k,v in item.items() if k not in ('token','workspace')} for item in self.entries.values()]
