"""Host-native execution lifecycle (ADR 0016); no workflow authority lives here.

Native CLIs and verifier commands run as the service user, with that user's own
login state, under an allowlisted environment and in their own process group.
There is NO isolation: no namespaces, cgroups, filesystem or network limits. This
module provides bounded admission, a durable process ledger, and positively
identified process-group termination, including after a runner restart.
"""
import asyncio
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
from uuid import uuid4
from cursus.contracts import Problem, canonical_json, validate

# Variables every child receives. Anything else must be listed explicitly in the
# configured `pass_env` (for example a CLI's own login-store session variables).
BASE_ENVIRONMENT = ('PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'TMPDIR')
DEFAULT_PATH = '/usr/local/bin:/usr/bin:/bin'


def utc():
    return datetime.now(timezone.utc).isoformat()


def start_ticks(pid):
    """Kernel start time of a process, or None when it does not exist."""
    try:
        # The command name may contain spaces/parentheses; fields follow the last ')'.
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


class HostRuntime:
    def __init__(self, settings, root, capacity):
        self.settings, self.capacity = settings, capacity
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.stat().st_uid != os.getuid():
            raise Problem('runtime_identity', 'Lifecycle directory must be owned by the runner user.')
        self.path = self.root / 'execution.json'
        self.temporary = self.root / 'tmp'
        self.temporary.mkdir(mode=0o700, exist_ok=True)
        self.entries = json.loads(self.path.read_text()) if self.path.exists() else {}
        if len(self.entries) > 32:
            raise Problem('runtime_state', 'Execution ledger exceeds bounded inventory.')
        self.boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.current = ContextVar('host_execution', default=None)
        self.lock = asyncio.Lock()
        self.owned = set()
        self.children = {}
        self.record = None
        # Termination waits; instance attributes so tests can shorten them.
        self.grace, self.kill_wait = 2.0, 5.0

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

    def fits(self, lane):
        # Ceilings are the concurrency limits; actual pressure can still delay starts.
        if sum(e['lane'] == lane for e in self.entries.values()) >= self.capacity[lane]:
            return False
        available = next(int(line.split()[1]) // 1024 for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:'))
        if available <= self.settings['host_reserve_mb']:
            return False
        return shutil.disk_usage(self.root).free >= self.settings['disk_reserve_mb'] * 1024 * 1024

    async def preflight(self):
        if shutil.disk_usage(self.root).free < self.settings['disk_reserve_mb'] * 1024 * 1024:
            raise Problem('runtime_boundary', 'Free disk is below the configured reserve.')
        if not os.access('/proc/meminfo', os.R_OK):
            raise Problem('runtime_boundary', 'Host memory pressure cannot be observed.')

    async def reserve(self, attempt, lane, cli=None):
        validate('Id', attempt)
        async with self.lock:
            if attempt in self.entries:
                raise Problem('state_conflict', 'Execution identity exists; relaunch forbidden.')
            if not self.fits(lane):
                return False
            self.entries[attempt] = dict(attempt=attempt, lane=lane, cli=cli, host_uid=os.getuid(),
                created=utc(), state='preparing', since=utc(), reason='Reserved before preparation.')
            self.save()
            if self.record:
                self.record('execution_intent', dict(self.entries[attempt]))
            self.owned.add(attempt)
            return True

    async def prepare(self, attempt, workspace, readonly=False):
        # `readonly` is advisory on the host: read-only roles rely on the CLI's
        # own read-only flags (required by Execution.authorize), not a mount.
        item = self.entries[attempt]
        workspace = Path(workspace)
        if not workspace.is_absolute() or workspace.is_symlink() or not workspace.is_dir() or workspace.stat().st_uid != os.getuid():
            raise Problem('mount_boundary', 'Workspace ownership/path is invalid.')
        (self.temporary / attempt).mkdir(mode=0o700, exist_ok=True)
        self.state(item, 'running', 'Native execution may run on the host.')

    def environment(self, argv, attempt):
        user = pwd.getpwuid(os.getuid())
        # The CLI's own directory first: script launchers resolve their interpreter beside it.
        path = self.settings.get('path', DEFAULT_PATH)
        if Path(argv[0]).is_absolute():
            path = str(Path(argv[0]).parent) + ':' + path
        value = {'PATH': path, 'HOME': user.pw_dir, 'USER': user.pw_name, 'LOGNAME': user.pw_name,
                 'LANG': 'C.UTF-8', 'TMPDIR': str(self.temporary / attempt)}
        for name in self.settings.get('pass_env', ()):
            if name in os.environ:
                value[name] = os.environ[name]
        return value

    async def spawn(self, argv, workspace, **kwargs):
        attempt = self.current.get()
        item = self.entries[attempt]
        if item['state'] != 'running':
            raise Problem('unknown_stop', 'Execution is not prepared on the host.')
        process = await asyncio.create_subprocess_exec(*argv, cwd=workspace,
            env=self.environment(argv, attempt), **kwargs)
        self.children.setdefault(attempt, []).append(process)
        # The child leads its own group (start_new_session); identity is recorded
        # before any output is consumed so a runner crash cannot lose it.
        ticks = start_ticks(process.pid)
        if ticks is not None:
            item['process'] = dict(pid=process.pid, start_ticks=ticks, boot_id=self.boot_id)
            self.save()
            if self.record:
                self.record('execution_identity', dict(item))
        return process

    @staticmethod
    def group_exists(pgid):
        try:
            os.killpg(pgid, 0)
            return True
        except ProcessLookupError:
            return False

    def identify(self, process):
        """'ours', 'gone' or 'foreign'. Never signals; foreign means the PID was reused."""
        if process['boot_id'] != self.boot_id:
            return 'gone'
        ticks = start_ticks(process['pid'])
        if ticks is not None:
            return 'ours' if ticks == process['start_ticks'] else 'foreign'
        # The leader is gone. The kernel does not reuse a PID while a group
        # carries it, so any surviving group with this ID is ours.
        try:
            return 'ours' if self.group_exists(process['pid']) else 'gone'
        except PermissionError:
            return 'foreign'

    async def terminate(self, attempt, process):
        if self.identify(process) != 'ours':
            return
        pgid = process['pid']
        for sig, wait in ((signal.SIGTERM, self.grace), (signal.SIGKILL, self.kill_wait)):
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                return
            except PermissionError:
                raise Problem('unknown_stop', 'Execution group cannot be signaled.') from None
            for child in self.children.get(attempt, ()):
                if child.returncode is None:
                    try:
                        await asyncio.wait_for(child.wait(), wait)
                    except TimeoutError:
                        pass
            deadline = asyncio.get_running_loop().time() + wait
            while self.group_exists(pgid):
                if asyncio.get_running_loop().time() >= deadline:
                    break
                await asyncio.sleep(.02)
            else:
                return
        raise Problem('unknown_stop', 'Execution group termination is not confirmed.')

    async def cleanup(self, attempt):
        item = self.entries.get(attempt)
        if item is None:
            return True
        try:
            if item.get('host_uid') != os.getuid():
                raise Problem('runtime_identity', 'Execution belongs to another user; reconcile manually.')
            self.state(item, 'stopping', 'Stopping the identified execution group.')
            if item.get('process'):
                await self.terminate(attempt, item['process'])
            shutil.rmtree(self.temporary / attempt, ignore_errors=True)
            if self.record:
                self.record('execution_removed', attempt)
            del self.entries[attempt]
            self.save()
            self.owned.discard(attempt)
            self.children.pop(attempt, None)
            return True
        except (OSError, ValueError, Problem, TimeoutError):
            self.state(item, 'uncertain', 'Group stop is unconfirmed; reservation retained. Automatic retry in 10s; inspect runner service diagnostics.')
            return False

    async def recover(self):
        # Only the bounded unresolved inventory; never scan every old attempt.
        results = {}
        for attempt in list(self.entries):
            if attempt not in self.owned:
                results[attempt] = await self.cleanup(attempt)
        return results

    def status(self):
        return [{k: v for k, v in item.items() if k != 'process'} for item in self.entries.values()]
